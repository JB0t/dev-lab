# Cluster Registry Runbook: Test Local Images In Any Cluster

A throwaway image registry inside a cluster you are cluster-admin on (AKS, EKS, kubeadm, k3s, kind: anything with containerd nodes), so local images run there without a publish pipeline and without leaving test artifacts in ACR or ECR. One script, `scripts/cluster-registry.sh`, does every step; the variables at the top of this page are the only things to change.

**How it works.** A `registry:2` Deployment behind a ClusterIP Service, plus a DaemonSet that listens on `127.0.0.1:5000` on every Linux node and forwards to the Service. Pods reference images as `localhost:5000/<image>`. containerd pulls `localhost` over plain HTTP without any node configuration, so no node is touched: no `hosts.toml`, no containerd restart, no custom CA. You push through a `kubectl port-forward` to `localhost:5050`, which Docker treats as insecure without configuration. The registry has no authentication and no TLS: it is reachable only from pods in the cluster and from the nodes' loopback, never from outside. Do not expose it with a LoadBalancer.

Because dev-lab's images are already named `localhost:5000/...` (the kind registry uses the same convention), its manifests run in the foreign cluster unchanged.

## Variables

Set these once in the shell you run the steps from. All have defaults; the first two are the ones to check.

```bash
export REG_CONTEXT=my-aks            # kubectl context of the foreign cluster (empty: the current one)
export REG_NAMESPACE=cluster-registry
export REG_NAME=registry
export REG_NODE_PORT=5000            # port on every node's loopback; images are localhost:$REG_NODE_PORT/<image>
export REG_LOCAL_PORT=5050           # port-forward on this machine for pushing (5000 is the kind registry locally)
export REG_SIZE=20Gi                 # registry volume, when the cluster has a StorageClass
export REG_STORAGE_CLASS=            # empty: the cluster's default; "none": emptyDir (images lost on pod restart)
export REG_IMAGE=registry:2.8.3
export REG_PROXY_IMAGE=alpine/socat:1.8.0.0
export REG_TEST_IMAGE=alpine:3.20    # a small public image "test" pushes and runs
export REG_TOLERATIONS=all           # proxy DaemonSet and test pod tolerations: all (operator Exists), none, or a JSON array
export REG_REGISTRY_TOLERATIONS=      # the registry pod's tolerations, same values (empty: REG_TOLERATIONS)
export REG_REGISTRY_NODE_SELECTOR='{}' # node labels for the registry pod, e.g. '{"agentpool":"system"}'
export REG_BUILD_IMAGE=docker:28.3-dind  # the in-cluster build pod (step 4b)
export REG_BUILD_SIZE=50Gi               # its layer cache (PVC when there is a StorageClass)
export REG_BUILD_STORAGE_CLASS=          # a disk class for the cache (empty: REG_STORAGE_CLASS/default; none: emptyDir)
export REG_BUILD_NODE_SELECTOR='{}'      # where it runs, e.g. '{"devlab.io/gpu":"true"}' or '{"agentpool":"gpu"}'
export REG_BUILD_TOLERATIONS=            # same values as REG_TOLERATIONS (empty: REG_TOLERATIONS)
export REG_BUILD_EXCLUDE=.git            # comma-separated tar patterns left out of the build context
cd ~/gh/jbotstevens/dev-lab          # or wherever the repo is; the script is scripts/cluster-registry.sh
```

Keep `REG_NODE_PORT=5000` unless a node already listens on it (step 2 reports that), so image names match the kind registry's `localhost:5000/...` and manifests need no change.

## 1. Check the cluster

```bash
scripts/cluster-registry.sh check
```

Prints the context, the platform (azure, aws, gcp or on-prem, from the nodes' provider IDs), whether you are cluster-admin, each node's OS, runtime and CPU architecture, and what storage the registry will use. The platform differences are handled here and in step 2; nothing else differs:

| Difference | Handled by |
|---|---|
| Default StorageClass (AKS `default`/`managed-csi`, EKS `gp2`/`gp3` only with the EBS CSI add-on, on-prem maybe none) | The PVC uses the cluster's default StorageClass; with none, the registry uses an emptyDir and `check` says which class to set in `REG_STORAGE_CLASS` |
| Pod Security Admission (on-prem clusters often enforce `baseline`, which forbids hostNetwork) | The namespace is created with the `privileged` PSA labels |
| Node taints (AKS `CriticalAddonsOnly`, GPU, Spot) | By default the proxy DaemonSet tolerates every taint (`operator: Exists`), so every node can pull. `REG_TOLERATIONS=none` tolerates nothing, and a JSON array is used as it is, e.g. `REG_TOLERATIONS='[{"key":"nvidia.com/gpu","operator":"Exists"}]'`. A tainted node without a proxy cannot pull from the registry. The registry pod takes `REG_REGISTRY_TOLERATIONS` (default: the same) and `REG_REGISTRY_NODE_SELECTOR`: on a cluster where every node pool is tainted it stays `Pending` with `untolerated taint` otherwise, and the cluster autoscaler reports `NotTriggerScaleUp` for the same reason |
| Windows node pools | The proxy and the registry select `kubernetes.io/os: linux`; Windows nodes cannot pull from it |
| EKS Fargate | Runs no DaemonSets; pods on Fargate cannot pull from it. `check` warns when Fargate nodes exist |
| Container runtime | containerd (AKS, EKS, kubeadm, k3s, kind) needs nothing. CRI-O needs `localhost:5000` as an insecure registry in `/etc/containers/registries.conf` on each node; `check` warns |
| CPU architecture (EKS Graviton, Azure Cobalt) | `check` warns when a node's architecture differs from your Docker's; build the image for it too (`docker buildx build --platform linux/arm64`) |
| Azure Policy / Gatekeeper forbidding hostNetwork | Not handled: ask for an exemption for the namespace, or run the registry elsewhere |

## 2. Install the registry

```bash
scripts/cluster-registry.sh up
```

Creates the namespace, the PVC (or not), the Deployment, the Service and the proxy DaemonSet, and waits for them. If the proxy pods never become ready, a node already uses `REG_NODE_PORT`: set another, e.g. `5005`, and run `up` again (image names then become `localhost:5005/...`). `scripts/cluster-registry.sh manifests` prints what is applied, for review or to keep.

## 3. Prove a node can pull from it

```bash
scripts/cluster-registry.sh test
```

Pulls `REG_TEST_IMAGE` locally, pushes it through the port-forward, runs it in the cluster as `localhost:5000/alpine:3.20` with `imagePullPolicy: Always`, and prints `PASS` with the node that pulled it. On `ErrImagePull` it prints the pull error, the node and the proxy pod on that node. The pod has the `REG_TOLERATIONS` tolerations, so on a mixed cluster run it a few times to land on different pools, or pin it: `kubectl run` with `--overrides` and a `nodeSelector`.

## 4. Push your images

```bash
scripts/cluster-registry.sh push localhost:5000/devlab-dask-gpu:2026.1.1 myapp:dev
```

Each image is tagged for the port-forward, pushed, and its in-cluster name printed. The registry host of a local name is dropped, so `localhost:5000/devlab-dask-gpu:2026.1.1` from the kind registry becomes `localhost:5000/devlab-dask-gpu:2026.1.1` in the cluster, and `myapp:dev` becomes `localhost:5000/myapp:dev`. Layers already in the registry are skipped, so a rebuild pushes only what changed. The push goes through the API server, which is slower than a direct registry: minutes for a multi-GB image the first time.

- An image that exists only in the kind registry (not in local Docker) needs `docker pull localhost:5000/<image>` first.
- Docker Desktop (Mac/Windows) runs the daemon in a VM that cannot reach the port-forward on the host's `localhost`. Use `crane` instead: `scripts/cluster-registry.sh forward` in one terminal, `crane copy myapp:dev localhost:5050/myapp:dev` in another.
- `scripts/cluster-registry.sh list` shows every repository and tag in the registry.

## 4b. Build in the cluster

For an image you cannot build on this machine: another CPU architecture, a build that needs a GPU node's disk, cores or memory, or no local Docker at all. The build runs in a Docker-in-Docker pod in the registry's namespace; the context directory is shipped to it over `kubectl exec` and a file of docker commands is run there.

```bash
# config/dask/image/cluster-build.sh:
#   docker buildx build -t "$REG/devlab-dask-gpu:2026.1.1" --push .
scripts/cluster-registry.sh build config/dask/image                   # runs DIR/cluster-build.sh
scripts/cluster-registry.sh build path/to/context path/to/build.sh    # or any file
```

The build file is a shell script (`sh -e`) run in the context directory on the pod, with `docker` and `docker buildx` available and two variables set: `REG`, the registry's in-cluster address to push to (`<REG_NAME>.<REG_NAMESPACE>.svc.cluster.local:5000`), and `REG_PULL`, the name pods use (`localhost:<REG_NODE_PORT>`). Tag images as `$REG/<name>:<tag>` and push them (`--push`, or `docker push`). From a terminal the build shows buildx's live progress as a local build does (plain step output otherwise), every command in the file is echoed with a `+`, and afterwards each tag the file names is checked in the registry: `Pushed (new digest ...). In the cluster: localhost:5000/<name>:<tag>`, or `NOT PUSHED` with a non-zero exit when the registry does not have it. Anything docker can do works: `--build-arg`, `-f`, `--target`, several builds, `docker run` for a smoke test.

- The first `build` creates the pod (`<REG_NAME>-builder`, privileged, as dockerd needs; the namespace already allows it) and a PVC of `REG_BUILD_SIZE` for its layer cache, so rebuilds reuse layers. Without a StorageClass the cache is an emptyDir and goes with the pod. The cache must be on a block disk (ext4/xfs): dockerd's overlay2 cannot run on Azure Files, EFS or NFS, so where such a class is the default, set `REG_BUILD_STORAGE_CLASS` to a disk class (`managed-csi` on AKS, `gp3` on EKS) or `none`. `check` warns when the class looks like a file share.
- `REG_BUILD_NODE_SELECTOR` and `REG_BUILD_TOLERATIONS` place it: on a GPU node, e.g. `'{"devlab.io/gpu":"true"}'`, or on whatever pool has the disk. Pulling a multi-GB base image happens on the node's network, not yours.
- `RUN` steps in a Dockerfile do not see the node's GPU, with Docker-in-Docker as with any builder; `nvcc` compiles without one. A GPU node is useful for its resources and its CPU architecture, not for running CUDA at build time.
- The context is sent as a tar each time (`REG_BUILD_EXCLUDE` leaves `.git` out; add build outputs there). A `.dockerignore` in the context still applies to the build itself.
- `scripts/cluster-registry.sh builder-down` removes the pod and its cache and keeps the registry; `down` removes both.

## 5. Point manifests and charts at it

Images are `localhost:$REG_NODE_PORT/<repository>:<tag>`. With `imagePullPolicy: IfNotPresent` and a tag you re-push (`dev`, `latest`), a node that already has the tag keeps the old image: use `Always`, or a new tag per build.

**dev-lab manifests** already use `localhost:5000/...`: `kubectl apply -k config/dask/sample` and the Dask cluster manifests from `devlab_dask.py` work as they are (with your own `kubectl`, not `devlab kubectl`, against the foreign context).

**Kustomize**: rewrite names without editing the manifests.

```yaml
# kustomization.yaml
images:
  - name: myregistry.azurecr.io/myapp
    newName: localhost:5000/myapp
    newTag: dev
```

**Helm**: most charts take the image in values.

```bash
helm upgrade --install myapp ./chart --set image.repository=localhost:5000/myapp --set image.tag=dev --set image.pullPolicy=Always
# charts with a registry value: --set image.registry=localhost:5000 --set image.repository=myapp
```

**Plain manifests**: `sed -i 's#myregistry.azurecr.io/#localhost:5000/#' deployment.yaml`, or `kubectl set image deployment/myapp myapp=localhost:5000/myapp:dev`.

No `imagePullSecrets` are needed; remove them for these images if a chart adds one for the registry it replaces.

## 6. Teardown

```bash
scripts/cluster-registry.sh down          # asks first
scripts/cluster-registry.sh down --yes
```

Deletes the namespace, with the registry, its images and its volume, and the build pod and its cache when they exist. Workloads still referencing `localhost:5000/...` keep running (the image is in the node's containerd cache) until they are rescheduled to a node that never pulled it; redeploy them from their real registry first. Nothing else was changed in the cluster, so nothing else needs undoing.

To keep the registry but reclaim space: `scripts/cluster-registry.sh forward`, delete tags with the registry API (`DELETE /v2/<repo>/manifests/<digest>`, enabled), then `kubectl -n $REG_NAMESPACE exec deploy/$REG_NAME -- registry garbage-collect /etc/docker/registry/config.yml`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `test` fails with `http: server gave HTTP response to HTTPS client` | The node's runtime does not default `localhost` to HTTP: CRI-O, or containerd with a `hosts.toml` for `localhost:5000` pointing elsewhere (a kind node created with a registry). Add `localhost:5000` as insecure in the runtime's config on that node, or use another `REG_NODE_PORT` |
| `test` fails with `connection refused` on `127.0.0.1:5000` | No proxy pod on that node: `kubectl -n $REG_NAMESPACE get pods -l app=$REG_NAME-proxy -o wide`. A Windows or Fargate node, or the DaemonSet was refused (PSA, Gatekeeper): `kubectl -n $REG_NAMESPACE describe daemonset $REG_NAME-proxy` |
| Proxy pods `CrashLoopBackOff` | Port in use on the node (`Address in use` in the pod log): change `REG_NODE_PORT` |
| `exec format error` when the pod starts | Image built for the wrong CPU architecture; `check` lists the nodes' |
| `docker push` to `localhost:5050` refused | Port-forward failed, likely the port is in use: change `REG_LOCAL_PORT` |
| Pod keeps an old build of the same tag | `imagePullPolicy: Always` or a new tag |
| Registry pod `Pending`, `node(s) had untolerated taint(s)` or `didn't match Pod's node affinity/selector` | Every node is tainted or none matches the selector: set `REG_REGISTRY_TOLERATIONS` (default `all` tolerates everything) or `REG_REGISTRY_NODE_SELECTOR`, run `up` again |
| `build`: pod not ready, `privileged` refused | Pod Security or Gatekeeper forbids privileged pods even in this namespace: no Docker-in-Docker there; build elsewhere and `push` |
| `build`: pod never ready, dockerd log ends in `error initializing graphdriver` (after `aufs is not supported` lines, which are harmless on their own) | The cache PVC is on a file share (Azure Files, EFS, NFS), where overlay2 cannot run: `builder-down`, set `REG_BUILD_STORAGE_CLASS` to a disk class or `none`, build again |
| `build`: `failed to solve: ... connection refused` or `http: server gave HTTP response` on push | The registry Service is not reachable from the build pod (NetworkPolicy?), or the `--insecure-registry` flag was lost: `kubectl -n $REG_NAMESPACE get deployment $REG_NAME-builder -o yaml | grep insecure` |
| Registry pod `Pending` with the PVC `Pending` | The StorageClass cannot provision (EKS without the EBS CSI add-on): `REG_STORAGE_CLASS=none` for an emptyDir, or install the driver |
