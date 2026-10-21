#!/usr/bin/env bash
# A throwaway image registry inside a cluster you are cluster-admin on, for testing
# local images there without publishing them. CLUSTER-REGISTRY-RUNBOOK.md has the steps.
#
#   cluster-registry.sh check          what the cluster is and what the registry will use
#   cluster-registry.sh up             install the registry and the node proxies
#   cluster-registry.sh test           push a small image and run it in the cluster
#   cluster-registry.sh push IMAGE...  push local Docker images; prints their in-cluster names
#   cluster-registry.sh build DIR [FILE]  build in the cluster: ship DIR to a Docker-in-Docker
#                                      pod and run the docker commands in FILE (DIR/cluster-build.sh)
#   cluster-registry.sh list           images in the registry
#   cluster-registry.sh forward        port-forward the registry to localhost (foreground)
#   cluster-registry.sh builder-down   remove the build pod and its cache, keep the registry
#   cluster-registry.sh down [--yes]   delete it all
#
# How it works: a registry Deployment behind a ClusterIP Service, and a DaemonSet that
# listens on 127.0.0.1:$REG_NODE_PORT on every node and forwards to the Service. Nodes
# pull "localhost:$REG_NODE_PORT/<image>" over plain HTTP, which containerd allows for
# localhost without any node configuration. You push through a kubectl port-forward on
# localhost:$REG_LOCAL_PORT, which Docker also treats as insecure without configuration.
# The registry has no authentication: it is reachable only from pods and node loopback.
#
# "build" is for images you cannot build locally (another CPU architecture, a GPU node's
# disk and cores, no local Docker): a privileged Docker-in-Docker pod in the namespace
# receives the build context over kubectl exec and runs your build file with docker,
# pushing to the registry at $REG (its in-cluster address). Its layer cache lives on a
# PVC when the cluster has a StorageClass.
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
# The registry pod's own tolerations (same values; default: REG_TOLERATIONS) and node
# selector, a JSON object merged with kubernetes.io/os=linux, e.g. '{"agentpool":"system"}'.
# On a cluster where every node is tainted the pod stays Pending without a toleration.
REG_REGISTRY_TOLERATIONS="${REG_REGISTRY_TOLERATIONS:-$REG_TOLERATIONS}"
REG_REGISTRY_NODE_SELECTOR="${REG_REGISTRY_NODE_SELECTOR:-{\}}"
# The build pod: image, cache size (PVC, else emptyDir), where it runs (a JSON node
# selector, e.g. '{"devlab.io/gpu":"true"}' for a GPU node, and tolerations as above),
# and what the context tar leaves out (comma-separated tar patterns).
REG_BUILD_IMAGE="${REG_BUILD_IMAGE:-docker:28.3-dind}"
REG_BUILD_SIZE="${REG_BUILD_SIZE:-50Gi}"
# StorageClass of the build cache (empty: REG_STORAGE_CLASS or the default; "none": emptyDir).
# It must be a block disk (ext4/xfs): overlay2 cannot run on Azure Files, EFS or NFS.
REG_BUILD_STORAGE_CLASS="${REG_BUILD_STORAGE_CLASS:-}"
REG_BUILD_NODE_SELECTOR="${REG_BUILD_NODE_SELECTOR:-{\}}"
REG_BUILD_TOLERATIONS="${REG_BUILD_TOLERATIONS:-$REG_TOLERATIONS}"
REG_BUILD_EXCLUDE="${REG_BUILD_EXCLUDE:-.git}"
# GPUs for the build pod (nvidia.com/gpu limit), for Dockerfiles whose RUN steps need one.
# Needs the GPU builder image (config/cluster-registry/gpu-builder, pushed with "push") as
# REG_BUILD_IMAGE and the legacy builder in the build file: DOCKER_BUILDKIT=0 docker build.
# REG_BUILD_RUNTIME_CLASS is the pod's RuntimeClass where the GPU runtime is not the default.
REG_BUILD_GPU="${REG_BUILD_GPU:-0}"
REG_BUILD_RUNTIME_CLASS="${REG_BUILD_RUNTIME_CLASS:-}"

# tolerations prints a tolerations setting (all, none or a JSON array) as a JSON array.
tolerations() {
    case "$1" in
        all) echo '[{"operator":"Exists"}]' ;;
        none) echo '[]' ;;
        *) printf '%s' "$1" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert isinstance(v, list); print(json.dumps(v))' 2>/dev/null \
               || die "REG_TOLERATIONS, REG_REGISTRY_TOLERATIONS and REG_BUILD_TOLERATIONS must be all, none or a JSON array of tolerations" ;;
    esac
}

# node_selector prints a JSON node selector setting merged with kubernetes.io/os=linux.
node_selector() {
    printf '%s' "$2" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert isinstance(v, dict); v.setdefault("kubernetes.io/os", "linux"); print(json.dumps(v))' 2>/dev/null \
        || die "$1 must be a JSON object of node labels"
}
registry_node_selector() { node_selector REG_REGISTRY_NODE_SELECTOR "$REG_REGISTRY_NODE_SELECTOR"; }
build_node_selector() { node_selector REG_BUILD_NODE_SELECTOR "$REG_BUILD_NODE_SELECTOR"; }

# registry_host is the registry's address inside the cluster, for pushes from pods.
registry_host() { echo "$REG_NAME.$REG_NAMESPACE.svc.cluster.local:5000"; }

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

# storage_class decides what the registry PVC uses: the variable, else the default, else none.
storage_class() { pick_storage_class "$REG_STORAGE_CLASS"; }
# build_storage_class is the same for the build cache, with its own variable first.
build_storage_class() { pick_storage_class "${REG_BUILD_STORAGE_CLASS:-$REG_STORAGE_CLASS}"; }
pick_storage_class() {
    if [ "$1" = none ]; then
        echo ""
    elif [ -n "$1" ]; then
        kubectl get storageclass "$1" >/dev/null || die "StorageClass $1 not found"
        echo "$1"
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
    say "Proxy tolerations: $(tolerations "$REG_TOLERATIONS")$([ "$REG_TOLERATIONS" = all ] || echo '  (tainted nodes without a matching toleration get no proxy and cannot pull)')"
    say "Registry pod: tolerations $(tolerations "$REG_REGISTRY_TOLERATIONS"), node selector $(registry_node_selector)"
    local bsc
    bsc="$(build_storage_class)"
    say "Build pod: tolerations $(tolerations "$REG_BUILD_TOLERATIONS"), node selector $(build_node_selector), cache $REG_BUILD_SIZE on ${bsc:-emptyDir}, GPUs $REG_BUILD_GPU"
    if [ -n "$bsc" ] && kubectl get storageclass "$bsc" -o jsonpath='{.provisioner}' | grep -qiE 'file|nfs|efs|smb|cifs'; then
        say "  $bsc looks like a file share: overlay2 cannot run on it. Set REG_BUILD_STORAGE_CLASS to a disk class (AKS managed-csi, EKS gp3) or none."
    fi
    if kn get deployment "$REG_NAME" >/dev/null 2>&1; then
        say "Installed: yes ($(kn get pods -l app="$REG_NAME-proxy" --no-headers 2>/dev/null | grep -c Running) proxy pods running)"
    else
        say "Installed: no"
    fi
    if kn get deployment "$REG_NAME-builder" >/dev/null 2>&1; then
        say "Build pod: installed ($(kn get pods -l app="$REG_NAME-builder" --no-headers 2>/dev/null | awk '{print $3}' | head -1))"
    fi
}

# builder_manifests prints the Docker-in-Docker build pod and its cache volume.
builder_manifests() {
    local sc="$1"
    if [ -n "$sc" ]; then
        cat <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $REG_NAME-builder
  namespace: $REG_NAMESPACE
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: $sc
  resources:
    requests:
      storage: $REG_BUILD_SIZE
---
EOF
    fi
    cat <<EOF
# Docker-in-Docker for "build": privileged, as dockerd needs; the build context arrives
# over kubectl exec and the images are pushed to the registry Service over plain HTTP.
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $REG_NAME-builder
  namespace: $REG_NAMESPACE
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: $REG_NAME-builder
  template:
    metadata:
      labels:
        app: $REG_NAME-builder
    spec:
      nodeSelector: $(build_node_selector)
      tolerations: $(tolerations "$REG_BUILD_TOLERATIONS")
$([ -n "$REG_BUILD_RUNTIME_CLASS" ] && echo "      runtimeClassName: $REG_BUILD_RUNTIME_CLASS")
      containers:
        - name: docker
          image: $REG_BUILD_IMAGE
          args:
            - --insecure-registry=$(registry_host)
            # Fail at once on a volume overlayfs cannot use, instead of probing every driver
            - --storage-driver=overlay2
          env:
            - name: DOCKER_TLS_CERTDIR
              value: ""
            - name: NVIDIA_DRIVER_CAPABILITIES
              value: all
          securityContext:
            privileged: true
          readinessProbe:
            exec:
              command: [docker, info]
            periodSeconds: 5
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
$([ "$REG_BUILD_GPU" != 0 ] && printf '            limits:\n              nvidia.com/gpu: "%s"\n' "$REG_BUILD_GPU")
          volumeMounts:
            - name: cache
              mountPath: /var/lib/docker
            - name: work
              mountPath: /work
      volumes:
        - name: work
          emptyDir: {}
        - name: cache
EOF
    if [ -n "$sc" ]; then
        cat <<EOF
          persistentVolumeClaim:
            claimName: $REG_NAME-builder
EOF
    else
        cat <<EOF
          emptyDir: {}
EOF
    fi
}

# builder_pod makes sure the build pod runs and prints its name.
builder_pod() {
    kn get service "$REG_NAME" >/dev/null || die "registry not installed: run $0 up"
    if ! kn get deployment "$REG_NAME-builder" >/dev/null 2>&1; then
        say "Creating the build pod (Docker-in-Docker) in $REG_NAMESPACE" >&2
        builder_manifests "$(build_storage_class)" | kubectl apply -f - >&2
    fi
    kn rollout status deployment "$REG_NAME-builder" --timeout=300s >&2 || {
        say "Build pod not ready (privileged pods refused? no node matches REG_BUILD_NODE_SELECTOR? the PVC?). Pod state:" >&2
        kn get pods -l app="$REG_NAME-builder" -o wide >&2
        kn describe pods -l app="$REG_NAME-builder" | grep -A3 '^Events' | tail -3 >&2
        say "Last dockerd log lines ('error initializing graphdriver' = the cache volume's filesystem cannot hold overlay2: set REG_BUILD_STORAGE_CLASS):" >&2
        kn logs -l app="$REG_NAME-builder" --tail=5 2>/dev/null | grep -v aufs >&2 || true
        exit 1
    }
    # The newest running pod that is not terminating (Recreate leaves the old one briefly)
    kn get pods -l app="$REG_NAME-builder" --field-selector status.phase=Running -o json | python3 -c '
import json, sys
pods = [p for p in json.load(sys.stdin)["items"] if not p["metadata"].get("deletionTimestamp")]
pods.sort(key=lambda p: p["metadata"]["creationTimestamp"], reverse=True)
print(pods[0]["metadata"]["name"] if pods else "")'
}

cmd_build() {
    need kubectl; need tar
    local dir="${1:-}" file="${2:-}"
    [ -n "$dir" ] && [ -d "$dir" ] || die "usage: $0 build DIR [FILE]   (FILE defaults to DIR/cluster-build.sh)"
    [ -n "$file" ] || file="$dir/cluster-build.sh"
    [ -f "$file" ] || die "no build file $file: a shell script of docker commands, run in the context directory with \$REG set"
    local pod pattern patterns excludes=()
    IFS=, read -ra patterns <<<"$REG_BUILD_EXCLUDE"
    for pattern in "${patterns[@]}"; do [ -n "$pattern" ] && excludes+=(--exclude "$pattern"); done
    pod="$(builder_pod)"
    [ -n "$pod" ] || die "no running build pod found"
    say "Sending $dir to $pod ($(du -sh "$dir" | cut -f1) before excludes)"
    # A fresh context directory in the pod each time, so deleted files do not linger
    kn exec "$pod" -- sh -c 'rm -rf /work/context && mkdir -p /work/context'
    tar czf - -C "$dir" "${excludes[@]}" . | kn exec -i "$pod" -- tar xzf - -C /work/context
    kn exec -i "$pod" -- sh -c 'cat > /work/cluster-build.sh' <"$file"
    say "In the pod: context $(kn exec "$pod" -- sh -c 'du -sh /work/context | cut -f1'), build file $(kn exec "$pod" -- wc -c /work/cluster-build.sh | cut -d' ' -f1) bytes (local: $(wc -c <"$file"))"
    local log="$dir/.cluster-build.log"
    say "Registry before the build: $(registry_snapshot "$pod" | wc -l | tr -d ' ') tags"
    registry_snapshot "$pod" >"$log.before"
    say "Running $file in the cluster with REG=$(registry_host) REG_PULL=localhost:$REG_NODE_PORT (each command is echoed with a +; full log in $log):"
    local started=$SECONDS tty=() progress="${BUILDKIT_PROGRESS:-plain}" status=0
    if [ -t 0 ] && [ -t 1 ]; then tty=(-it); progress="${BUILDKIT_PROGRESS:-auto}"; fi   # a terminal: buildx's live progress, as locally
    local legacy=""
    [ "$REG_BUILD_GPU" = 0 ] || legacy="DOCKER_BUILDKIT=0"   # docker build then uses the legacy builder, whose RUN steps get the GPU
    kn exec "${tty[@]}" "$pod" -- sh -c "set -o pipefail; cd /work/context && REG='$(registry_host)' REG_PULL='localhost:$REG_NODE_PORT' BUILDKIT_PROGRESS=$progress $legacy sh -ex /work/cluster-build.sh 2>&1 | tee /work/build.log" \
        || status=$?
    kn exec "$pod" -- cat /work/build.log | tr -d '\r' >"$log"
    registry_snapshot "$pod" >"$log.after"
    say ""
    say "The build file $([ $status -eq 0 ] && echo finished || echo "FAILED with exit code $status") after $((SECONDS - started))s. What it did, from its trace and the registry:"
    build_report "$log" || status=1
    rm -f "$log.before" "$log.after"
    [ $status -eq 0 ] || exit $status
}

# registry_snapshot prints "repo:tag digest" for every tag in the registry, asked from a pod.
registry_snapshot() {
    kn exec "$1" -- sh -c '
H="'"$(registry_host)"'"
A="Accept: application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json"
for repo in $(wget -qO- "http://$H/v2/_catalog?n=1000" | tr "," "\n" | sed -n "s/.*\"\([^\"]*\)\".*/\1/p" | grep -v "^repositories$"); do
    tags=$(wget -qO- "http://$H/v2/$repo/tags/list" | grep "\"tags\":\[" | sed "s/.*\"tags\":\[\([^]]*\)\].*/\1/" | tr "," "\n" | sed -n "s/\"\([^\"]*\)\"/\1/p")
    for tag in $tags; do
        echo "$repo:$tag $(wget -qO- --header "$A" "http://$H/v2/$repo/manifests/$tag" | sha256sum | cut -c1-12)"
    done
done
exit 0'
}

# build_report reads the build trace: every image the docker commands tagged or pushed under
# the registry's address, and whether the registry has it now (new, same or missing).
build_report() {
    REG_HOST="$(registry_host)" REG_PULL_HOST="localhost:$REG_NODE_PORT" python3 - "$1" <<'PY'
import os, re, shlex, sys
log = sys.argv[1]
host, pull = os.environ["REG_HOST"], os.environ["REG_PULL_HOST"]
def snapshot(path):
    out = {}
    for line in open(path):
        parts = line.split()
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out
before, after = snapshot(log + ".before"), snapshot(log + ".after")
lines = open(log, errors="replace").read().splitlines()
traced = [l for l in lines if l.startswith("+ ")]
docker = [l for l in traced if re.match(r"\+ (sudo )?docker\b", l)]
wanted = []
def want(name):
    if name.startswith(host + "/"):
        name = name[len(host) + 1:]
        if ":" not in name.rsplit("/", 1)[-1]:
            name += ":latest"
        if name not in wanted:
            wanted.append(name)
for line in docker:
    try:
        words = shlex.split(line[2:])
    except ValueError:
        words = line[2:].split()
    for i, word in enumerate(words):
        if word in ("-t", "--tag") and i + 1 < len(words):
            want(words[i + 1])
        elif word.startswith(("-t=", "--tag=")):
            want(word.split("=", 1)[1])
        elif word.startswith("--output") or word.startswith("-o"):
            value = word.split("=", 1)[1] if "=" in word else (words[i + 1] if i + 1 < len(words) else "")
            m = re.search(r"name=([^,]+)", value)
            if m:
                want(m.group(1))
    if len(words) >= 3 and words[1] == "push":
        want(words[-1])
    if len(words) >= 4 and words[1] == "tag":
        want(words[-1])
problems = 0
if not docker:
    print("  No docker command ran. The trace of the build file was:")
    for l in traced or ["  (nothing: the file has no commands, or they are all comments)"]:
        print("   " + l)
    sys.exit(1)
print("  Docker commands that ran:")
for l in docker:
    print("   " + (l if len(l) < 200 else l[:197] + "..."))
if not wanted:
    print(f"  None of them tagged or pushed an image under {host}/ ($REG). Nothing could reach the registry.")
    print(f"  Tag the build -t \"$REG/<name>:<tag>\" and push it (--push, or docker push).")
    problems += 1
for name in wanted:
    if name in after and name not in before:
        print(f"  Pushed (new, digest {after[name]}). In the cluster: {pull}/{name}")
    elif name in after and after[name] != before[name]:
        print(f"  Pushed (updated, digest {before[name]} -> {after[name]}). In the cluster: {pull}/{name}")
    elif name in after:
        print(f"  Pushed (same digest {after[name]} as before: identical to what the registry had). In the cluster: {pull}/{name}")
    else:
        problems += 1
        print(f"  NOT PUSHED: {pull}/{name} is not in the registry. Why, from the trace:")
        cmds = [l for l in docker if host + "/" + name.rsplit(":", 1)[0] in l]
        pushed = any("--push" in l or " push " in l for l in cmds)
        if not pushed:
            print(f"   - no command pushed it: the build has no --push and nothing ran 'docker push {host}/{name}' (a --load or a plain docker build only stores it in the build pod)")
        errors = [l for l in lines if re.search(r"error|denied|refused|failed|unauthorized|no such host|HTTPS client", l, re.I) and not l.startswith("+ ")]
        for l in errors[-5:]:
            print("   - " + l.strip()[:200])
        repo = name.rsplit(":", 1)[0]
        tags = sorted(k.split(":", 1)[1] for k in after if k.rsplit(":", 1)[0] == repo)
        print(f"   - the registry has for {repo}: {', '.join(tags) if tags else 'nothing'}")
changed = {k: v for k, v in after.items() if before.get(k) != v and k not in wanted}
for name, digest in sorted(changed.items()):
    print(f"  Also changed in the registry during the build: {pull}/{name} (digest {digest})")
sys.exit(1 if problems else 0)
PY
}

cmd_builder_down() {
    need kubectl
    kn delete deployment "$REG_NAME-builder" --ignore-not-found
    kn delete pvc "$REG_NAME-builder" --ignore-not-found
    say "Build pod and its cache removed; the registry stays."
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
      nodeSelector: $(registry_node_selector)
      tolerations: $(tolerations "$REG_REGISTRY_TOLERATIONS")
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
      tolerations: $(tolerations "$REG_TOLERATIONS")
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
    tolerations "$REG_TOLERATIONS" >/dev/null; tolerations "$REG_REGISTRY_TOLERATIONS" >/dev/null; registry_node_selector >/dev/null
    say "Installing registry $REG_NAME in $REG_NAMESPACE on $(kubectl config current-context) ($(platform)); storage: ${sc:-emptyDir}"
    manifests "$sc" | kubectl apply -f -
    kn rollout status deployment "$REG_NAME" --timeout=180s || {
        say "Registry pod not ready. If it is Pending with 'untolerated taint' or no node matches, set REG_REGISTRY_TOLERATIONS"
        say "or REG_REGISTRY_NODE_SELECTOR and run up again; if its PVC is Pending, see REG_STORAGE_CLASS. Pod state:"
        kn get pods -l app="$REG_NAME" -o wide
        kn describe pods -l app="$REG_NAME" | grep -A3 '^Events' | tail -3
        exit 1
    }
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
        docker image inspect "$image" >/dev/null 2>&1 \
            || die "$image is not in the local Docker. An image in a registry only (the kind one at localhost:5000) needs: docker pull $image"
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
        --overrides="{\"spec\":{\"tolerations\":$(tolerations "$REG_TOLERATIONS")}}" -- sh -c 'echo pulled from the cluster registry' >/dev/null
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
    build) shift; cmd_build "$@" ;;
    list) cmd_list ;;
    forward) cmd_forward ;;
    builder-down) cmd_builder_down ;;
    down) shift; cmd_down "$@" ;;
    manifests) manifests "$(storage_class)"; echo ---; builder_manifests "$(build_storage_class)" ;;
    *) sed -n '2,15p' "$0"; exit 1 ;;
esac
