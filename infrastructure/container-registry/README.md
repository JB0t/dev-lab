# container-registry

<!-- docgen:begin id=infrastructure/container-registry:overview scope=infrastructure/container-registry hash=7788277bc77b -->
This module defines the infrastructure for a container registry within a Kubernetes cluster, specifically tailored for a `dev-lab` environment. It includes the core registry service, its configuration, storage setup, and a web-based user interface for easier management. The registry is deployed as a DaemonSet to run on control-plane nodes, ensuring it's accessible across the cluster.

The module uses a `Kustomization` base to manage the deployment, which references a `docker-registry.yaml` file containing all necessary Kubernetes resources. These include a `Namespace`, `DaemonSet`, `ConfigMap`, `Service`, `Deployment`, `Service`, and `Ingress` for the registry and its UI. The registry is configured to use hostPath storage for persistence and is exposed via a ClusterIP service, with a NodePort service and an Ingress for external access.

The structure allows for easy deployment and management of a local container registry using standard Kubernetes primitives. The `DaemonSet` ensures the registry runs on each control-plane node, while the `Deployment` and `Service` provide a web UI for interacting with the registry. The `Ingress` resource enables access to the UI through a defined hostname, making it accessible externally.
<!-- docgen:end id=infrastructure/container-registry:overview -->

<!-- docgen:begin id=infrastructure/container-registry:reference scope=infrastructure/container-registry hash=7788277bc77b -->
## Reference

### `docker-registry.yaml`

- **`Namespace/dev-lab-registry`** (manifest)
- **`DaemonSet/docker-registry`** (manifest)
- **`ConfigMap/registry-config`** (manifest)
- **`Service/docker-registry`** (manifest)
- **`Deployment/docker-registry-ui`** (manifest)
- **`Service/docker-registry-ui`** (manifest)
- **`Ingress/registry-ui-ingress`** (manifest)

### `kustomization.yaml`

- **`Kustomization/dev-lab-registry`** (manifest)
<!-- docgen:end id=infrastructure/container-registry:reference -->
