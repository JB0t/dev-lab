# prometheus-stack

<!-- docgen:begin id=infrastructure/prometheus-stack:overview scope=infrastructure/prometheus-stack hash=5499acf1cdb6 -->
This module deploys a Prometheus-based monitoring stack using Helm charts through GitOps with FluxCD. It defines a `monitoring` namespace and configures two Helm repositories: one for Prometheus community charts and another for Grafana charts. The stack is deployed as a `HelmRelease` named `kube-prometheus-stack`, which includes Prometheus, Grafana, Alertmanager, and various exporters.

The configuration is optimized for local development environments with reduced resource limits and faster startup times. It disables several Kubernetes component exporters and tunes Prometheus settings like scrape and evaluation intervals, retention policies, and service types to NodePort for easy access. Grafana is pre-configured with default dashboards, admin credentials, and additional plugins.

The module uses `kustomize` to manage the deployment, with a `Kustomization` resource that references the main `prometheus-stack.yaml` file. The stack is designed to be lightweight and suitable for development environments while maintaining the core monitoring functionality provided by the `kube-prometheus-stack` Helm chart.
<!-- docgen:end id=infrastructure/prometheus-stack:overview -->

<!-- docgen:begin id=infrastructure/prometheus-stack:reference scope=infrastructure/prometheus-stack hash=5499acf1cdb6 -->
## Reference

### `kustomization.yaml`

- **`Kustomization/dev-lab-prometheus-stack`** (manifest)

### `prometheus-stack.yaml`

- **`Namespace/monitoring`** (manifest)
- **`HelmRepository/prometheus-community`** (manifest)
- **`HelmRepository/grafana`** (manifest)
- **`HelmRelease/kube-prometheus-stack`** (manifest)
<!-- docgen:end id=infrastructure/prometheus-stack:reference -->
