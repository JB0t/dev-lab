# node-autoscaler

<!-- docgen:begin id=config/addons/node-autoscaler:overview scope=config/addons/node-autoscaler hash=b8c748713f4a -->
This module configures the cluster-autoscaler with a kwok cloud provider to enable node autoscaling in a development environment. It defines the necessary Helm values and Node templates that allow the autoscaler to simulate node provisioning and management without requiring actual cloud infrastructure. The configuration is designed for use with devlab and KinD clusters, where nodes are created as Kubernetes Node objects from templates.

The module consists of two main configuration files: `cluster-autoscaler-values.yaml` which sets up the autoscaler chart with kwok-specific settings, and `kwok-provider.yaml` which provides Node templates for different node pools. The autoscaler uses these templates to create Node objects that represent potential worker nodes, with each template defining resource capacity, labels, and annotations for scaling behavior.

The `kwok-provider.yaml` file defines a ConfigMap containing Node templates that the autoscaler's kwok provider uses to simulate node creation. These templates are applied to the cluster after the Helm release and are grouped by labels to define different node pools. The autoscaler's expander strategy selects between these pools based on resource efficiency, and nodes created from templates are tainted to ensure only workloads that explicitly tolerate the taint and select the appropriate node pool will be scheduled on them.
<!-- docgen:end id=config/addons/node-autoscaler:overview -->

<!-- docgen:begin id=config/addons/node-autoscaler:reference scope=config/addons/node-autoscaler hash=b8c748713f4a -->
## Reference

### `kwok-provider.yaml`

- **`ConfigMap/kwok-provider-templates`** (manifest)
<!-- docgen:end id=config/addons/node-autoscaler:reference -->
