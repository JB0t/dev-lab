# monitoring

<!-- docgen:begin id=infrastructure/monitoring:overview scope=infrastructure/monitoring hash=643e098e8532 -->
This module defines the monitoring infrastructure for a Kubernetes cluster using Prometheus and Grafana. It sets up the `monitoring` namespace and deploys the kube-prometheus-stack Helm chart to provide core monitoring capabilities. The module includes configurations for scraping metrics from Linkerd service mesh components and Flagger progressive delivery system.

The module uses `ServiceMonitor` and `PodMonitor` custom resources to define which metrics to scrape from different parts of the system. It configures Linkerd monitoring with separate monitors for controller components, control plane services, and proxy metrics. Flagger metrics are exposed through a dedicated ServiceMonitor. Grafana dashboards are provided via ConfigMap to visualize the monitoring data.

The `kustomization.yaml` file ties together all the monitoring resources into a single deployment. It references the Prometheus stack, Linkerd monitors, Flagger monitor, and Grafana dashboard ConfigMap. The Prometheus stack is configured with reduced resource limits and disabled components to optimize for local development. The Grafana dashboard provides detailed visualization of Linkerd canary deployments and traffic management.
<!-- docgen:end id=infrastructure/monitoring:overview -->

<!-- docgen:begin id=infrastructure/monitoring:reference scope=infrastructure/monitoring hash=643e098e8532 -->
## Reference

### `flagger-servicemonitor.yaml`

- **`ServiceMonitor/flagger`** (manifest)

### `grafana-dashboard-configmap.yaml`

- **`ConfigMap/linkerd-canary-dashboard`** (manifest)

### `kustomization.yaml`

- **`Kustomization/dev-lab-monitoring`** (manifest)

### `linkerd-podmonitor-simple.yaml`

- **`PodMonitor/linkerd-proxy-simple`** (manifest)

### `linkerd-servicemonitors.yaml`

- **`ServiceMonitor/linkerd-controller`** (manifest)
- **`ServiceMonitor/linkerd-control-plane`** (manifest)
- **`PodMonitor/linkerd-proxy`** (manifest)

### `prometheus-stack.yaml`

- **`Namespace/monitoring`** (manifest)
- **`HelmRepository/prometheus-community`** (manifest)
- **`HelmRepository/grafana`** (manifest)
- **`HelmRelease/kube-prometheus-stack`** (manifest)
<!-- docgen:end id=infrastructure/monitoring:reference -->
