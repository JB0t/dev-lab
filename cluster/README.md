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
