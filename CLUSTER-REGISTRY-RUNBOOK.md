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
export REG_BUILD_GPU=0                   # GPUs for the build pod, with the GPU builder image (step 4c)
export REG_BUILD_RUNTIME_CLASS=          # the build pod's RuntimeClass where the GPU runtime is not the node default
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

One image, followed through. Start from what `docker image ls` shows on this machine:

```
REPOSITORY                  TAG    IMAGE ID
myacr.azurecr.io/team/base  1.0    3f2a9c1b0d4e
```

```bash
image=myacr.azurecr.io/team/base:1.0          # exactly as docker image ls shows it, REPOSITORY:TAG
scripts/cluster-registry.sh push "$image"
# Pushed. In the cluster: localhost:5000/team/base:1.0
```

The same image now has three names, and which one to use depends on where you are:

| Where | Name | Why |
|---|---|---|
| This machine (`docker image ls`) | `myacr.azurecr.io/team/base:1.0` | The local name; `push` takes it as it is |
| In the registry (`list`) | `team/base:1.0` | A registry stores the path only. `push` drops the registry host (`myacr.azurecr.io/`, `localhost:5000/`, anything with a dot or a port); a plain `base:1.0` stays `base:1.0` |
| A pod in the cluster | `localhost:5000/team/base:1.0` | `REG_PULL`: the nodes' loopback, which the proxy forwards to the registry |
| The build pod (step 4b) | `$REG/team/base:1.0` | `REG`: the registry's Service address, since a pod has no proxy on its own loopback |

`list` prints the registry's names with the `localhost:5000/` prefix, ready to paste into a manifest. Layers already in the registry are skipped, so a rebuild pushes only what changed. The push goes through the API server, slower than a direct registry: minutes for a multi-GB image the first time.

- `push` wants the image in the local Docker. One that exists only in a registry (the kind one at `localhost:5000`, or ACR) needs `docker pull "$image"` first; `push` says so.
- Docker Desktop (Mac/Windows) runs the daemon in a VM that cannot reach the port-forward on the host's `localhost`. Use `crane` instead: `scripts/cluster-registry.sh forward` in one terminal, `crane copy "$image" localhost:5050/team/base:1.0` in another.

## 4b. Build in the cluster

For an image you cannot build on this machine: another CPU architecture, a build that needs a GPU node's disk, cores or memory, or no local Docker at all. The build runs in a Docker-in-Docker pod in the registry's namespace; the context directory is shipped to it over `kubectl exec` and a file of docker commands is run there, with two variables set:

| Variable | Value | Use it for |
|---|---|---|
| `REG` | `<REG_NAME>.<REG_NAMESPACE>.svc.cluster.local:5000` | Every image name in the build: the base image to pull, the tag to push |
| `REG_PULL` | `localhost:<REG_NODE_PORT>` | Only for printing the name pods will use |

Continuing the example: build `team/app:dev` on top of the `team/base:1.0` pushed in step 4. The context directory:

```
app/
├── Dockerfile
└── cluster-build.sh
```

```dockerfile
# app/Dockerfile. ARG before FROM, or FROM cannot see it.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY . /app
```

```bash
# app/cluster-build.sh: a shell script run by sh -e in the context directory on the build pod.
# The base image is the registry name from step 4 behind $REG; --pull takes a re-pushed base
# instead of the pod's cached copy; --push sends the result to the registry.
docker buildx build --pull --build-arg BASE_IMAGE="$REG/team/base:1.0" -t "$REG/team/app:dev" --push .
```

```bash
scripts/cluster-registry.sh build app          # runs app/cluster-build.sh
scripts/cluster-registry.sh build app other.sh # or any file
```

What it prints, in order: the context and build file sizes as received in the pod; every command of the file echoed with a `+`, variables expanded; everything the commands print, buildx's live progress included (from a terminal, as a local build shows it; plain step output otherwise); then a report built from that trace and from the registry's contents before and after, not from the file:

```
The build file finished after 212s. What it did, from its trace and the registry:
  Docker commands that ran:
   + docker buildx build --pull --build-arg BASE_IMAGE=registry.cluster-registry.svc.cluster.local:5000/team/base:1.0 -t registry.cluster-registry.svc.cluster.local:5000/team/app:dev --push .
  Pushed (new, digest 717ed6e82934). In the cluster: localhost:5000/team/app:dev
```

Every image a docker command tagged or pushed under `$REG/` is checked: `Pushed (new ...)`, `Pushed (updated, digest a -> b)`, `Pushed (same digest ... as before)`, or `NOT PUSHED` with the reason from the trace (no `--push` and no `docker push`, or the error lines docker printed) and what the registry holds for that repository, with a non-zero exit. A build file whose docker commands are silenced (`-q`, output redirected) still shows the commands that ran. The whole output is kept in `DIR/.cluster-build.log`. The image then goes into a manifest as `localhost:5000/team/app:dev` (step 5).

The three ways a base image from the registry fails, and the fix:

- `$REG/myacr.azurecr.io/team/base:1.0` or `$REG/localhost:5000/team/base:1.0`: the registry holds `team/base:1.0`, the name `list` prints without its `localhost:5000/` prefix. Use `$REG/team/base:1.0`.
- `FROM $REG/team/base:1.0` in the Dockerfile: `REG` is a variable of the build file's shell, not of the Dockerfile. Pass it as a build arg, as above.
- `ARG BASE_IMAGE` placed after `FROM`: a `FROM` sees only the `ARG`s declared before it.

To test a name from inside the build pod, independent of any build file:

```bash
kubectl -n "$REG_NAMESPACE" exec deploy/"$REG_NAME"-builder -- docker pull "$REG_NAME.$REG_NAMESPACE.svc.cluster.local:5000/team/base:1.0"
```

Anything docker can do works in the build file: `-f`, `--target`, several builds, `docker run` for a smoke test.

- The first `build` creates the pod (`<REG_NAME>-builder`, privileged, as dockerd needs; the namespace already allows it) and a PVC of `REG_BUILD_SIZE` for its layer cache, so rebuilds reuse layers. Without a StorageClass the cache is an emptyDir and goes with the pod. The cache must be on a block disk (ext4/xfs): dockerd's overlay2 cannot run on Azure Files, EFS or NFS, so where such a class is the default, set `REG_BUILD_STORAGE_CLASS` to a disk class (`managed-csi` on AKS, `gp3` on EKS) or `none`. `check` warns when the class looks like a file share.
- `REG_BUILD_NODE_SELECTOR` and `REG_BUILD_TOLERATIONS` place it: on a GPU node, e.g. `'{"devlab.io/gpu":"true"}'`, or on whatever pool has the disk. Pulling a multi-GB base image happens on the node's network, not yours.
- `RUN` steps do not see a GPU with the default builder (BuildKit runs them with plain runc), even on a GPU node; `nvcc` compiles without one. For a Dockerfile that needs the GPU at build time, see step 4c.
- The context is sent as a tar each time (`REG_BUILD_EXCLUDE` leaves `.git` out; add build outputs there). A `.dockerignore` in the context still applies to the build itself.
- The dev-lab image: `scripts/cluster-registry.sh build config/dask/image` runs `config/dask/image/cluster-build.sh`, one `docker buildx build -t "$REG/devlab-dask-gpu:2026.1.1" --push .`.
- `scripts/cluster-registry.sh builder-down` removes the pod and its cache and keeps the registry; `down` removes both.

## 4c. Build with a GPU

For a Dockerfile whose `RUN` steps need the GPU (a self-test, a JIT cache, a build that probes the device). BuildKit cannot do it: `docker buildx build` runs `RUN` steps with plain runc, with no devices and no driver. The legacy builder can, because its `RUN` steps are ordinary containers of the inner daemon, and with the NVIDIA Container Toolkit as that daemon's default runtime they get the pod's GPU. Verified: inside the GPU builder image a `RUN nvidia-smi -L` step lists the GPU under `DOCKER_BUILDKIT=0 docker build`, and fails with `nvidia-smi: not found` under `docker buildx build`.

Three things, once:

```bash
# 1. The GPU builder image: Docker-in-Docker on Ubuntu with the NVIDIA Container Toolkit. No GPU needed to build it.
#    build.sh copies the trusted CA certificates from python/certs into the image first (TLS inspection:
#    the downloads during the build, and the inner dockerd's image pulls, trust them)
config/cluster-registry/gpu-builder/build.sh gpu-builder:1
scripts/cluster-registry.sh push gpu-builder:1
# 2. The build pod from it, with a GPU (the nvidia.com/gpu limit also lands it on a GPU node)
scripts/cluster-registry.sh builder-down            # if a build pod exists already
export REG_BUILD_IMAGE=localhost:5000/gpu-builder:1 REG_BUILD_GPU=1
# 3. Where the GPU runtime is not the nodes' default (a GPU Operator install without it), the RuntimeClass:
export REG_BUILD_RUNTIME_CLASS=nvidia
```

Then in the Dockerfile, the GPU steps need the NVIDIA variables set before them, and the build file uses the legacy builder and a separate push:

```dockerfile
FROM nvidia/cuda:12.4.1-base-ubuntu22.04
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility
RUN nvidia-smi -L                       # sees the pod's GPU
```

```bash
# cluster-build.sh: DOCKER_BUILDKIT=0 is set for you when REG_BUILD_GPU is not 0
docker build -t "$REG/team/gpu-app:dev" .
docker push "$REG/team/gpu-app:dev"
```

The legacy builder has no `--push`, `--mount`, `--platform` or multi-stage parallelism, and Docker prints a deprecation notice for it; `docker buildx build` in the same file still works for steps that need no GPU. `ENV` is per stage: a stage from an outside image needs the NVIDIA variables again, one from an earlier stage of yours inherits them, and `ENV NVIDIA_VISIBLE_DEVICES=void` in a stage keeps the GPU out of its steps. With `REG_BUILD_GPU=0` the same image runs containers with plain runc, so it serves as the build pod for ordinary builds too (behind TLS inspection it is the one with your certificates). The GPU is shared with nothing else while the build pod holds it; `builder-down` frees it. On AKS and EKS GPU nodes the NVIDIA runtime is the nodes' default, so `REG_BUILD_RUNTIME_CLASS` stays empty.

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
| `build` with `REG_BUILD_GPU`: `RUN` step says `nvidia-smi: not found` or `libcuda.so.1` missing | The step ran under BuildKit: use `docker build` (the legacy builder; `DOCKER_BUILDKIT=0` is set) not `docker buildx build`, and `ENV NVIDIA_VISIBLE_DEVICES=all` before the step |
| Building `gpu-builder`: `SSL certificate problem` from curl or apt | TLS inspection: put the proxy's CA as a `.crt` under `python/certs/` and build with `config/cluster-registry/gpu-builder/build.sh`, which installs it before the downloads. The default `docker:dind` build pod has no such certificates, so behind inspection use the GPU builder image for every build, with `REG_BUILD_GPU=0` when no GPU is needed |
| `build` with `REG_BUILD_GPU`: pod `Pending`, `Insufficient nvidia.com/gpu` | No free GPU, or a Dask worker holds them all: scale the workers down, or `REG_BUILD_NODE_SELECTOR` onto another pool |
| `build`: `failed to solve: ... connection refused` or `http: server gave HTTP response` on push | The registry Service is not reachable from the build pod (NetworkPolicy?), or the `--insecure-registry` flag was lost: `kubectl -n $REG_NAMESPACE get deployment $REG_NAME-builder -o yaml | grep insecure` |
| Registry pod `Pending` with the PVC `Pending` | The StorageClass cannot provision (EKS without the EBS CSI add-on): `REG_STORAGE_CLASS=none` for an emptyDir, or install the driver |
