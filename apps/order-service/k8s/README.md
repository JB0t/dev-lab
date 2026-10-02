# k8s

<!-- docgen:begin id=apps/order-service/k8s:overview scope=apps/order-service/k8s hash=054eda93c9fe -->
This module defines the Kubernetes manifests for deploying and managing the `order-service` application, including its base deployment, canary release configuration, and supporting resources. It uses `kustomize` to compose a consistent set of manifests under the `order-system` namespace, integrating with Linkerd for service mesh observability and Flagger for progressive delivery.

The base resources include a `Deployment`, `Service`, and `Ingress` for the application itself, along with a `Namespace` configured for automatic Linkerd proxy injection. The canary configuration enables gradual traffic shifts using Flagger, incorporating custom metric templates and webhook-based tests to validate service health and performance during deployments.

Supporting manifests define a `PodMonitor` for collecting Linkerd proxy metrics, a `Deployment` and `Service` for the Flagger load tester, and several `MetricTemplate` resources that provide query definitions for success rate, latency, and traffic-based metrics. These components work together to enable automated, safe rollouts with comprehensive monitoring and testing.
<!-- docgen:end id=apps/order-service/k8s:overview -->

<!-- docgen:begin id=apps/order-service/k8s:reference scope=apps/order-service/k8s hash=054eda93c9fe -->
## Reference

### `base.yaml`

- **`Namespace/order-system`** (manifest)
- **`Deployment/order-service`** (manifest)
- **`Service/order-service`** (manifest)
- **`Ingress/order-service-ingress`** (manifest)

### `canary.yaml`

- **`Canary/order-service`** (manifest)

### `kustomization.yaml`

- **`Kustomization/`** (manifest)

### `linkerd-podmonitor.yaml`

- **`PodMonitor/order-service-linkerd-proxy`** (manifest)

### `loadtester.yaml`

- **`Deployment/flagger-loadtester`** (manifest)
- **`Service/flagger-loadtester`** (manifest)

### `metrics.yaml`

- **`MetricTemplate/linkerd-success-rate`** (manifest)
- **`MetricTemplate/linkerd-request-duration`** (manifest)
- **`MetricTemplate/linkerd-traffic-success-rate`** (manifest)
<!-- docgen:end id=apps/order-service/k8s:reference -->
