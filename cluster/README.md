# cluster

<!-- docgen:begin id=cluster:overview scope=cluster hash=8c6b4a99acb5 -->
This module defines a KinD cluster configuration for local development. It creates a multi-node Kubernetes setup with one control plane and two worker nodes. All nodes get the label `ingress-ready=true` to support NGINX ingress controller.

The configuration sets up networking with custom pod and service subnets. It maps container ports to host ports for registry, ingress controller, Prometheus, and Grafana. The control plane node mounts a local registry directory at `/tmp/dev-lab-registry`.

Container runtime uses `containerd` with registry mirrors configured to point to the local control plane registry. This setup enables local image building and testing without external dependencies. The cluster name is `dev-lab` and API server listens on port 6443.
<!-- docgen:end id=cluster:overview -->

<!-- docgen:begin id=cluster:reference scope=cluster hash=8c6b4a99acb5 -->
## Reference

### `kind-config.yaml`

- **`Cluster/`** (manifest)
<!-- docgen:end id=cluster:reference -->

## GPU-Enabled Variant (nvkind)

`bin/devlab bootstrap --gpu` creates the cluster from these files instead of `kind-config.yaml`. They use [nvkind](https://github.com/NVIDIA/nvkind)'s template format, and `devlab` renders them itself (nvkind is not needed):

- `nvkind-config-template.yaml`: the same cluster as `kind-config.yaml`, with worker nodes generated from the values file. It is a Go template with [sprig](https://masterminds.github.io/sprig/) functions and `numGPUs`.
- `nvkind-values.yaml`: one `workers` entry per worker node. `devices` assigns host GPUs to that worker by index, list of indexes, or `all`. Omit it for a CPU-only worker.

Keep the shared parts of both files in sync. `go test ./...` (internal/lab) fails when they drift. See the GPU section of the top-level README for host setup.
