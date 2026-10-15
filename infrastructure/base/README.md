# base

<!-- docgen:begin id=infrastructure/base:overview scope=infrastructure/base hash=9092500ee7bf -->
This module defines base infrastructure for a Kubernetes development environment. It creates a `dev-lab-system` namespace and a `dev-lab-config` ConfigMap with cluster settings. The module includes core services like the metrics server for horizontal pod autoscaling.

The module uses Kustomize to manage Kubernetes resources. The `kustomization.yaml` file defines the base name and namespace. It references `core-services.yaml` which contains all infrastructure manifests.

The `core-services.yaml` file defines multiple Kubernetes resources. It creates a metrics server deployment in the `kube-system` namespace. It also defines ClusterRoles, RoleBindings, and ClusterRoleBindings for metrics server permissions. The module sets up a Service for metrics server and an APIService to expose metrics endpoints. The metrics server uses a dedicated ServiceAccount with restricted permissions.
<!-- docgen:end id=infrastructure/base:overview -->

<!-- docgen:begin id=infrastructure/base:reference scope=infrastructure/base hash=9092500ee7bf -->
## Reference

### `core-services.yaml`

- **`Namespace/dev-lab-system`** (manifest)
- **`ConfigMap/dev-lab-config`** (manifest)
- **`ServiceAccount/metrics-server`** (manifest)
- **`ClusterRole/system:aggregated-metrics-reader`** (manifest)
- **`ClusterRole/system:metrics-server`** (manifest)
- **`RoleBinding/metrics-server-auth-reader`** (manifest)
- **`ClusterRoleBinding/metrics-server:system:auth-delegator`** (manifest)
- **`ClusterRoleBinding/system:metrics-server`** (manifest)
- **`Service/metrics-server`** (manifest)
- **`Deployment/metrics-server`** (manifest)
- **`APIService/v1beta1.metrics.k8s.io`** (manifest)

### `kustomization.yaml`

- **`Kustomization/dev-lab-base-infrastructure`** (manifest)
<!-- docgen:end id=infrastructure/base:reference -->
