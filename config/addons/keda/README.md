# keda

<!-- docgen:begin id=config/addons/keda:overview scope=config/addons/keda hash=4b88428e6fa9 -->
This module provides configuration values for the KEDA (Kubernetes Event-Driven Autoscaling) addon, which is installed using the `devlab addon enable keda` command. It defines resource limits and requests for the KEDA operator, metric server, and webhooks components, as well as configuration for integrating with Prometheus monitoring through ServiceMonitors.

The configuration is structured around Prometheus integration, with options to enable or disable monitoring for both the KEDA operator and its metric server. ServiceMonitors are configured with labels that allow the `kube-prometheus-stack` to scrape metrics, ensuring that KEDA's metrics are properly exposed and collected. Each component has defined CPU and memory requests and limits to control resource allocation.

The module's structure follows a hierarchical pattern where top-level values like `prometheus` contain nested configurations for `operator`, each with their own monitoring and resource settings. Resource configurations are organized by component, making it easy to adjust compute resources for different parts of the KEDA deployment independently.
<!-- docgen:end id=config/addons/keda:overview -->

<!-- docgen:begin id=config/addons/keda:reference scope=config/addons/keda hash=4b88428e6fa9 -->
## Reference

### `values.yaml`

- **`prometheus`** (value)
- **`prometheus.metricServer`** (value)
- **`prometheus.metricServer.enabled`** (value)
- **`prometheus.metricServer.serviceMonitor`** (value)
- **`prometheus.metricServer.serviceMonitor.enabled`** (value)
- **`prometheus.metricServer.serviceMonitor.additionalLabels`** (value)
- **`prometheus.metricServer.serviceMonitor.additionalLabels.release`** (value)
- **`prometheus.operator`** (value)
- **`prometheus.operator.enabled`** (value)
- **`prometheus.operator.serviceMonitor`** (value)
- **`prometheus.operator.serviceMonitor.enabled`** (value)
- **`prometheus.operator.serviceMonitor.additionalLabels`** (value)
- **`prometheus.operator.serviceMonitor.additionalLabels.release`** (value)
- **`resources`** (value)
- **`resources.operator`** (value)
- **`resources.operator.requests`** (value)
- **`resources.operator.requests.cpu`** (value)
- **`resources.operator.requests.memory`** (value)
- **`resources.operator.limits`** (value)
- **`resources.operator.limits.cpu`** (value)
- **`resources.operator.limits.memory`** (value)
- **`resources.metricServer`** (value)
- **`resources.metricServer.requests`** (value)
- **`resources.metricServer.requests.cpu`** (value)
- **`resources.metricServer.requests.memory`** (value)
- **`resources.metricServer.limits`** (value)
- **`resources.metricServer.limits.cpu`** (value)
- **`resources.metricServer.limits.memory`** (value)
- **`resources.webhooks`** (value)
- **`resources.webhooks.requests`** (value)
- **`resources.webhooks.requests.cpu`** (value)
- **`resources.webhooks.requests.memory`** (value)
- **`resources.webhooks.limits`** (value)
- **`resources.webhooks.limits.cpu`** (value)
- **`resources.webhooks.limits.memory`** (value)
<!-- docgen:end id=config/addons/keda:reference -->
