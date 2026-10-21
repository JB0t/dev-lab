#!/usr/bin/env bash
# A throwaway image registry inside a cluster you are cluster-admin on, for testing
# local images there without publishing them. CLUSTER-REGISTRY-RUNBOOK.md has the steps.
#
#   cluster-registry.sh check          what the cluster is and what the registry will use
#   cluster-registry.sh up             install the registry and the node proxies
#   cluster-registry.sh test           push a small image and run it in the cluster
#   cluster-registry.sh push IMAGE...  push local Docker images; prints their in-cluster names
#   cluster-registry.sh list           images in the registry
#   cluster-registry.sh forward        port-forward the registry to localhost (foreground)
#   cluster-registry.sh down [--yes]   delete it all
#
# How it works: a registry Deployment behind a ClusterIP Service, and a DaemonSet that
# listens on 127.0.0.1:$REG_NODE_PORT on every node and forwards to the Service. Nodes
# pull "localhost:$REG_NODE_PORT/<image>" over plain HTTP, which containerd allows for
# localhost without any node configuration. You push through a kubectl port-forward on
# localhost:$REG_LOCAL_PORT, which Docker also treats as insecure without configuration.
# The registry has no authentication: it is reachable only from pods and node loopback.
set -euo pipefail

# Variables: set them in the environment before running, or take the defaults.
REG_CONTEXT="${REG_CONTEXT:-}"                      # kubectl context (empty: the current one)
REG_NAMESPACE="${REG_NAMESPACE:-cluster-registry}"
REG_NAME="${REG_NAME:-registry}"
REG_NODE_PORT="${REG_NODE_PORT:-5000}"              # port on every node's loopback; images are localhost:$REG_NODE_PORT/...
REG_LOCAL_PORT="${REG_LOCAL_PORT:-5050}"            # port-forward on this machine for pushing (5000 is often taken locally)
REG_SIZE="${REG_SIZE:-20Gi}"                        # PVC size, when the cluster has a default StorageClass
REG_STORAGE_CLASS="${REG_STORAGE_CLASS:-}"          # StorageClass (empty: the default one; "none": emptyDir, lost on restart)
REG_IMAGE="${REG_IMAGE:-registry:2.8.3}"
REG_PROXY_IMAGE="${REG_PROXY_IMAGE:-alpine/socat:1.8.0.0}"
REG_TEST_IMAGE="${REG_TEST_IMAGE:-alpine:3.20}"     # pulled locally by "test"
# Tolerations of the proxy DaemonSet and the test pod: "all" (operator Exists, every
# tainted node gets a proxy), "none", or a JSON array used as it is, e.g.
# '[{"key":"nvidia.com/gpu","operator":"Exists"}]'
REG_TOLERATIONS="${REG_TOLERATIONS:-all}"

# tolerations prints the configured tolerations as a JSON array.
tolerations() {
    case "$REG_TOLERATIONS" in
        all) echo '[{"operator":"Exists"}]' ;;
        none) echo '[]' ;;
        *) printf '%s' "$REG_TOLERATIONS" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert isinstance(v, list); print(json.dumps(v))' 2>/dev/null \
               || die "REG_TOLERATIONS must be all, none or a JSON array of tolerations" ;;
    esac
}

kubectl() { command kubectl ${REG_CONTEXT:+--context "$REG_CONTEXT"} "$@"; }
kn() { kubectl -n "$REG_NAMESPACE" "$@"; }
say() { printf '%s\n' "$*"; }
die() { say "error: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed"; }

# platform: azure, aws or on-prem, from the nodes' provider IDs (informational; only the
# default StorageClass fallback differs by platform).
platform() {
    local ids
    ids="$(kubectl get nodes -o jsonpath='{.items[*].spec.providerID}' 2>/dev/null || true)"
    case "$ids" in
        azure://*) echo azure ;;
        aws://*) echo aws ;;
        gce://*) echo gcp ;;
        *) echo on-prem ;;
    esac
}

# default_storage_class prints the cluster's default StorageClass, or nothing.
default_storage_class() {
    kubectl get storageclass -o json 2>/dev/null | python3 -c '
import json, sys
for item in json.load(sys.stdin).get("items", []):
    notes = item["metadata"].get("annotations", {})
    if notes.get("storageclass.kubernetes.io/is-default-class") == "true" or notes.get("storageclass.beta.kubernetes.io/is-default-class") == "true":
        print(item["metadata"]["name"]); break'
}

# storage_class decides what the PVC uses: the variable, else the default, else none.
storage_class() {
    if [ "$REG_STORAGE_CLASS" = none ]; then
        echo ""
    elif [ -n "$REG_STORAGE_CLASS" ]; then
        kubectl get storageclass "$REG_STORAGE_CLASS" >/dev/null || die "StorageClass $REG_STORAGE_CLASS not found"
        echo "$REG_STORAGE_CLASS"
    else
        default_storage_class
    fi
}

cmd_check() {
    need kubectl
    say "Context:   $(kubectl config current-context)"
    say "Platform:  $(platform)"
    local admin
    admin="$(kubectl auth can-i '*' '*' 2>/dev/null || true)"
    say "Cluster-admin: $admin"
    [ "$admin" = yes ] || say "  (not cluster-admin: the namespace, hostNetwork DaemonSet or PSA label may be refused)"
    say "Nodes (name, OS, runtime):"
    kubectl get nodes -o custom-columns='NAME:.metadata.name,OS:.status.nodeInfo.operatingSystem,RUNTIME:.status.nodeInfo.containerRuntimeVersion,ARCH:.status.nodeInfo.architecture' --no-headers | sed 's/^/  /'
    if kubectl get nodes -o jsonpath='{.items[*].status.nodeInfo.containerRuntimeVersion}' | grep -qv containerd; then
        say "  A node runs a runtime other than containerd. CRI-O needs 'localhost:$REG_NODE_PORT' as an insecure"
        say "  registry in /etc/containers/registries.conf on each node; containerd needs nothing."
    fi
    if kubectl get nodes -o jsonpath='{.items[*].status.nodeInfo.architecture}' | tr ' ' '\n' | sort -u | grep -qv "$(docker version -f '{{.Server.Arch}}' 2>/dev/null || uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"; then
        say "  Some nodes have another CPU architecture than this machine's Docker: build the images for theirs too."
    fi
    if kubectl get nodes -l eks.amazonaws.com/compute-type=fargate --no-headers 2>/dev/null | grep -q .; then
        say "  Fargate nodes run no DaemonSets: pods there cannot pull from this registry."
    fi
    local sc
    sc="$(storage_class)"
    if [ -n "$sc" ]; then
        say "Storage:   PVC of $REG_SIZE on StorageClass $sc"
    else
        say "Storage:   emptyDir (no default StorageClass: images are lost when the registry pod restarts;"
        case "$(platform)" in
            azure) say "            AKS has managed-csi: REG_STORAGE_CLASS=managed-csi)" ;;
            aws) say "            EKS needs the EBS CSI add-on for gp2/gp3: REG_STORAGE_CLASS=gp3 once it is installed)" ;;
            *) say "            set REG_STORAGE_CLASS to one of: $(kubectl get storageclass -o name | sed 's|storageclass.storage.k8s.io/||' | tr '\n' ' '))" ;;
        esac
    fi
    say "Registry:  namespace $REG_NAMESPACE, name $REG_NAME, nodes pull localhost:$REG_NODE_PORT/<image>, push via localhost:$REG_LOCAL_PORT"
    say "Proxy tolerations: $(tolerations)$([ "$REG_TOLERATIONS" = all ] || echo '  (tainted nodes without a matching toleration get no proxy and cannot pull)')"
    if kn get deployment "$REG_NAME" >/dev/null 2>&1; then
        say "Installed: yes ($(kn get pods -l app="$REG_NAME-proxy" --no-headers 2>/dev/null | grep -c Running) proxy pods running)"
    else
        say "Installed: no"
    fi
}

# manifests prints everything "up" applies.
manifests() {
    local sc="$1"
    cat <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: $REG_NAMESPACE
  labels:
    # The proxy uses hostNetwork, which Pod Security Admission refuses below privileged
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/warn: privileged
---
EOF
    if [ -n "$sc" ]; then
        cat <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $REG_NAME
  namespace: $REG_NAMESPACE
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: $sc
  resources:
    requests:
      storage: $REG_SIZE
---
EOF
    fi
    cat <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $REG_NAME
  namespace: $REG_NAMESPACE
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: $REG_NAME
  template:
    metadata:
      labels:
        app: $REG_NAME
    spec:
      nodeSelector:
        kubernetes.io/os: linux
      containers:
        - name: registry
          image: $REG_IMAGE
          env:
            - name: REGISTRY_STORAGE_DELETE_ENABLED
              value: "true"
          ports:
            - containerPort: 5000
          readinessProbe:
            httpGet:
              path: /v2/
              port: 5000
          resources:
            requests:
              cpu: 50m
              memory: 128Mi
          volumeMounts:
            - name: data
              mountPath: /var/lib/registry
      volumes:
        - name: data
EOF
    if [ -n "$sc" ]; then
        cat <<EOF
          persistentVolumeClaim:
            claimName: $REG_NAME
EOF
    else
        cat <<EOF
          emptyDir: {}
EOF
    fi
    cat <<EOF
---
apiVersion: v1
kind: Service
metadata:
  name: $REG_NAME
  namespace: $REG_NAMESPACE
spec:
  selector:
    app: $REG_NAME
  ports:
    - port: 5000
      targetPort: 5000
---
# On every Linux node: 127.0.0.1:$REG_NODE_PORT forwards to the registry Service, so
# containerd pulls localhost:$REG_NODE_PORT/<image> over plain HTTP with no node config.
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: $REG_NAME-proxy
  namespace: $REG_NAMESPACE
spec:
  selector:
    matchLabels:
      app: $REG_NAME-proxy
  template:
    metadata:
      labels:
        app: $REG_NAME-proxy
    spec:
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      nodeSelector:
        kubernetes.io/os: linux
      tolerations: $(tolerations)
      containers:
        - name: proxy
          image: $REG_PROXY_IMAGE
          args:
            - TCP-LISTEN:$REG_NODE_PORT,bind=127.0.0.1,fork,reuseaddr
            - TCP:$REG_NAME.$REG_NAMESPACE.svc.cluster.local:5000
          readinessProbe:
            tcpSocket:
              host: 127.0.0.1
              port: $REG_NODE_PORT
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
EOF
}

cmd_up() {
    need kubectl
    local sc
    sc="$(storage_class)"
    tolerations >/dev/null
    say "Installing registry $REG_NAME in $REG_NAMESPACE on $(kubectl config current-context) ($(platform)); storage: ${sc:-emptyDir}"
    manifests "$sc" | kubectl apply -f -
    kn rollout status deployment "$REG_NAME" --timeout=180s
    kn rollout status daemonset "$REG_NAME-proxy" --timeout=180s || {
        say "Proxy pods not ready. A node may already use port $REG_NODE_PORT: pick another REG_NODE_PORT. Pod state:"
        kn get pods -l app="$REG_NAME-proxy" -o wide
        exit 1
    }
    say "Ready. Nodes pull localhost:$REG_NODE_PORT/<image>; next: $0 test, then $0 push IMAGE..."
}

# with_forward runs a command with the registry port-forwarded to localhost:$REG_LOCAL_PORT.
with_forward() {
    kn get service "$REG_NAME" >/dev/null || die "registry not installed: run $0 up"
    kn port-forward "service/$REG_NAME" "$REG_LOCAL_PORT:5000" >/dev/null 2>&1 &
    local pid=$!
    trap "kill $pid 2>/dev/null" EXIT
    local tries=0
    until curl -fs "http://localhost:$REG_LOCAL_PORT/v2/" >/dev/null 2>&1; do
        tries=$((tries + 1))
        [ $tries -lt 50 ] || die "port-forward to localhost:$REG_LOCAL_PORT did not come up (port in use? set REG_LOCAL_PORT)"
        sleep 0.2
    done
    "$@"
    kill $pid 2>/dev/null
    trap - EXIT
}

# image_path strips a registry host (something with a dot or a port, or localhost) from an
# image name, keeping repository and tag: localhost:5000/devlab-dask-gpu:1 -> devlab-dask-gpu:1.
image_path() {
    local image="$1" first
    first="${image%%/*}"
    if [ "$first" != "$image" ] && { [[ "$first" == *.* ]] || [[ "$first" == *:* ]] || [ "$first" = localhost ]; }; then
        echo "${image#*/}"
    else
        echo "$image"
    fi
}

push_images() {
    local image path
    for image in "$@"; do
        path="$(image_path "$image")"
        [[ "$path" == *:* ]] || path="$path:latest"
        docker tag "$image" "localhost:$REG_LOCAL_PORT/$path"
        docker push "localhost:$REG_LOCAL_PORT/$path"
        docker rmi "localhost:$REG_LOCAL_PORT/$path" >/dev/null
        say "Pushed. In the cluster: localhost:$REG_NODE_PORT/$path"
    done
}

cmd_push() {
    need kubectl; need docker; need curl
    [ $# -gt 0 ] || die "usage: $0 push IMAGE..."
    with_forward push_images "$@"
}

cmd_list() {
    need kubectl; need curl
    with_forward sh -c '
        for repo in $(curl -fs "http://localhost:'"$REG_LOCAL_PORT"'/v2/_catalog" | python3 -c "import json,sys; print(\" \".join(json.load(sys.stdin).get(\"repositories\") or []))"); do
            tags=$(curl -fs "http://localhost:'"$REG_LOCAL_PORT"'/v2/$repo/tags/list" | python3 -c "import json,sys; print(\", \".join(json.load(sys.stdin).get(\"tags\") or []))")
            echo "localhost:'"$REG_NODE_PORT"'/$repo  tags: $tags"
        done'
}

cmd_forward() {
    need kubectl
    kn get service "$REG_NAME" >/dev/null || die "registry not installed: run $0 up"
    say "Registry on http://localhost:$REG_LOCAL_PORT (docker push localhost:$REG_LOCAL_PORT/<image>); Ctrl-C to stop"
    kn port-forward "service/$REG_NAME" "$REG_LOCAL_PORT:5000"
}

cmd_test() {
    need kubectl; need docker; need curl
    local path
    path="$(image_path "$REG_TEST_IMAGE")"
    say "Pulling $REG_TEST_IMAGE locally and pushing it"
    docker pull -q "$REG_TEST_IMAGE" >/dev/null
    with_forward push_images "$REG_TEST_IMAGE"
    say "Running localhost:$REG_NODE_PORT/$path in the cluster"
    kn delete pod "$REG_NAME-test" --ignore-not-found >/dev/null
    kn run "$REG_NAME-test" --image="localhost:$REG_NODE_PORT/$path" --image-pull-policy=Always --restart=Never \
        --overrides="{\"spec\":{\"tolerations\":$(tolerations)}}" -- sh -c 'echo pulled from the cluster registry' >/dev/null
    local phase="" tries=0
    while [ "$phase" != Succeeded ] && [ $tries -lt 60 ]; do
        sleep 2
        phase="$(kn get pod "$REG_NAME-test" -o jsonpath='{.status.phase}')"
        tries=$((tries + 1))
        if kn get pod "$REG_NAME-test" -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}' 2>/dev/null | grep -Eq 'ErrImagePull|ImagePullBackOff'; then
            say "The pull failed:"
            kn describe pod "$REG_NAME-test" | grep -E 'Failed|Error' | tail -3
            say "Node and proxy pod on it:"
            kn get pod "$REG_NAME-test" -o jsonpath='{.spec.nodeName}{"\n"}'
            kn get pods -l app="$REG_NAME-proxy" -o wide --field-selector "spec.nodeName=$(kn get pod "$REG_NAME-test" -o jsonpath='{.spec.nodeName}')"
            exit 1
        fi
    done
    [ "$phase" = Succeeded ] || die "test pod is $phase after 2 minutes: kubectl -n $REG_NAMESPACE describe pod $REG_NAME-test"
    say "PASS: node $(kn get pod "$REG_NAME-test" -o jsonpath='{.spec.nodeName}') pulled localhost:$REG_NODE_PORT/$path and ran it"
    kn delete pod "$REG_NAME-test" >/dev/null
}

cmd_down() {
    need kubectl
    kubectl get namespace "$REG_NAMESPACE" >/dev/null 2>&1 || { say "Namespace $REG_NAMESPACE does not exist; nothing to remove."; return; }
    if [ "${1:-}" != --yes ]; then
        say "This deletes namespace $REG_NAMESPACE with the registry, its images and its volume on $(kubectl config current-context)."
        printf 'Continue? [y/N] '
        read -r answer
        [ "$answer" = y ] || [ "$answer" = Y ] || { say "Kept."; return; }
    fi
    kubectl delete namespace "$REG_NAMESPACE" --wait=true
    say "Removed. Images the nodes already pulled stay in their containerd cache until pruned."
}

case "${1:-}" in
    check) cmd_check ;;
    up) cmd_up ;;
    test) cmd_test ;;
    push) shift; cmd_push "$@" ;;
    list) cmd_list ;;
    forward) cmd_forward ;;
    down) shift; cmd_down "$@" ;;
    manifests) manifests "$(storage_class)" ;;
    *) sed -n '2,12p' "$0"; exit 1 ;;
esac
