# cluster

<!-- docgen:begin id=cluster:overview scope=cluster hash=159c406bd2ec -->
This module provides configurations for creating Kubernetes clusters using KinD (Kubernetes in Docker) tailored for different environments. It includes two primary configuration files: one for continuous integration setups and another for local development, both defining a cluster with a control-plane node and worker nodes, along with specific networking and container runtime settings.

The configurations define a `Cluster` resource of API version `kind.x-k8s.io/v1alpha4`, specifying networking parameters such as pod and service subnets, API server port, and node roles. Each configuration maps essential ports like 5000 (registry), 80 (HTTP), and 443 (HTTPS) from the host to the control-plane node, enabling local access to services and registry.

The cluster configurations also include containerd registry mirrors and TLS settings to support local image registries, ensuring that container images can be pulled from a locally hosted registry running within the cluster. The configurations are designed to be used with the `kind` tool to create consistent and reproducible development and CI environments.
<!-- docgen:end id=cluster:overview -->

<!-- docgen:begin id=cluster:reference scope=cluster hash=159c406bd2ec -->
## Reference

### `kind-config.ci.yaml`

- **`Cluster/`** (manifest)

### `kind-config.yaml`

- **`Cluster/`** (manifest)
<!-- docgen:end id=cluster:reference -->
