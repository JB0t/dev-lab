# base

<!-- docgen:begin id=infrastructure/base:overview scope=infrastructure/base hash=9092500ee7bf -->
This module defines the base infrastructure for a development environment, centered around the `dev-lab-system` namespace and foundational Kubernetes resources. It includes configuration settings, a metrics server setup, and necessary RBAC bindings to support monitoring and horizontal pod autoscaling. The structure is managed using Kustomize, with a base `kustomization.yaml` file that references core services defined in `core-services.yaml`.

The core services include a `Namespace` for organizing resources, a `ConfigMap` for environment-specific settings, and a `Deployment` for the `metrics-server` component. The metrics server is configured with appropriate `ServiceAccount`, `ClusterRole`, and `ClusterRoleBinding` resources to enable access to node and pod metrics. Additionally, it defines a `Service` and `APIService` to expose metrics via the Kubernetes API.

The module's components work together to provide a minimal but functional base for infrastructure that supports monitoring and scaling capabilities. The `kustomization.yaml` file ties all these resources into a single deployable unit under the `dev-lab-base-infrastructure` name and `dev-lab-system` namespace, ensuring consistent application of the base configuration across environments.
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
