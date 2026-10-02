# templates

<!-- docgen:begin id=templates:overview scope=templates hash=abf034d5fc72 -->
This module provides a collection of Kubernetes manifest templates for deploying and managing services with canary releases, monitoring, and load testing. It includes templates for base deployments, canary strategies, load testing, metrics, and monitoring, all designed to work together to enable automated and safe rollouts of applications.

The templates are structured to support a complete canary deployment workflow using Flagger, with components such as `Canary`, `Deployment`, `Service`, `Ingress`, `Kustomization`, `MetricTemplate`, and `PodMonitor`. Each template uses placeholders like `SERVICE_NAME_PLACEHOLDER` and `PORT_PLACEHOLDER` to allow for dynamic configuration during deployment.

The module's components interconnect through shared naming conventions and namespaces, with the `Kustomization` template serving as the entry point that aggregates all other manifests. The `Canary` template references `MetricTemplate` resources for analysis and integrates with a `flagger-loadtester` deployment for performing health checks and load tests, while `PodMonitor` provides detailed metrics for accurate canary evaluation.
<!-- docgen:end id=templates:overview -->

<!-- docgen:begin id=templates:reference scope=templates hash=abf034d5fc72 -->
## Reference

### `base-template.yaml`

- **`Namespace/SERVICE_NAME_PLACEHOLDER`** (manifest)
- **`Deployment/SERVICE_NAME_PLACEHOLDER`** (manifest)
- **`Service/SERVICE_NAME_PLACEHOLDER`** (manifest)
- **`Ingress/SERVICE_NAME_PLACEHOLDER-ingress`** (manifest)

### `canary-template.yaml`

- **`Canary/SERVICE_NAME_PLACEHOLDER`** (manifest)

### `kustomization-template.yaml`

- **`Kustomization/`** (manifest)

### `loadtester-template.yaml`

- **`Deployment/flagger-loadtester`** (manifest)
- **`Service/flagger-loadtester`** (manifest)

### `metrics-template.yaml`

- **`MetricTemplate/linkerd-success-rate`** (manifest)
- **`MetricTemplate/linkerd-request-duration`** (manifest)
- **`MetricTemplate/linkerd-traffic-success-rate`** (manifest)

### `podmonitor-template.yaml`

- **`PodMonitor/SERVICE_NAME_PLACEHOLDER-linkerd-proxy`** (manifest)
<!-- docgen:end id=templates:reference -->
