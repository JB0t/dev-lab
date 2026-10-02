# infrastructure

<!-- docgen:begin id=infrastructure:overview scope=infrastructure hash=8f7dac40919e -->
This module defines the infrastructure setup for a development lab environment using Kubernetes manifests and Kustomize configurations. It provides a structured approach to deploying core services, container registries, networking components, progressive delivery tools, and monitoring systems. The module is organized into multiple directories that represent different aspects of the infrastructure, each with its own Kustomization file to manage resource deployment.

The infrastructure is composed of several key components that build upon each other in a specific order. Core services like the metrics server are deployed first to provide essential metrics capabilities. Networking is handled through an ingress controller, followed by a container registry for local image storage and management. Progressive delivery is enabled via Flagger, which integrates with service mesh technologies, and monitoring is implemented using Prometheus and Grafana stacks. Each component is configured with appropriate resource limits, security settings, and monitoring capabilities.

The module uses Kustomize to manage multiple layered deployments, with each subdirectory containing specific resources and a `kustomization.yaml` file that defines how those resources should be assembled and applied. The main `infrastructure/kustomization.yaml` file orchestrates the overall deployment order, ensuring that dependencies are met before deploying dependent components. This modular approach allows for easy customization and maintenance of the infrastructure while maintaining clear separation of concerns between different functional areas.
<!-- docgen:end id=infrastructure:overview -->

<!-- docgen:begin id=infrastructure:reference scope=infrastructure hash=8f7dac40919e -->
## Reference

### `base/core-services.yaml`

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

### `base/kustomization.yaml`

- **`Kustomization/dev-lab-base-infrastructure`** (manifest)

### `container-registry/docker-registry.yaml`

- **`Namespace/dev-lab-registry`** (manifest)
- **`DaemonSet/docker-registry`** (manifest)
- **`ConfigMap/registry-config`** (manifest)
- **`Service/docker-registry`** (manifest)
- **`Deployment/docker-registry-ui`** (manifest)
- **`Service/docker-registry-ui`** (manifest)
- **`Ingress/registry-ui-ingress`** (manifest)

### `container-registry/kustomization.yaml`

- **`Kustomization/dev-lab-registry`** (manifest)

### `flagger/flagger.yaml`

- **`HelmRepository/flagger`** (manifest)
- **`HelmRelease/flagger`** (manifest)

### `flagger/kustomization.yaml`

- **`Kustomization/flagger`** (manifest)

### `flagger/trafficsplit-crd.yaml`

- **`CustomResourceDefinition/trafficsplits.split.smi-spec.io`** (manifest)

### `kustomization.yaml`

- **`Kustomization/dev-lab-infrastructure`** (manifest)

### `monitoring/flagger-servicemonitor.yaml`

- **`ServiceMonitor/flagger`** (manifest)

### `monitoring/kustomization.yaml`

- **`Kustomization/dev-lab-monitoring-extras`** (manifest)

### `monitoring/prometheus-stack.yaml`

- **`Namespace/monitoring`** (manifest)
- **`HelmRepository/prometheus-community`** (manifest)
- **`HelmRepository/grafana`** (manifest)
- **`HelmRelease/kube-prometheus-stack`** (manifest)

### `networking/ingress-nginx.yaml`

- **`Namespace/ingress-nginx`** (manifest)
- **`Deployment/ingress-nginx-controller`** (manifest)
- **`Service/ingress-nginx-controller`** (manifest)
- **`ServiceAccount/ingress-nginx`** (manifest)
- **`ConfigMap/ingress-nginx-controller`** (manifest)
- **`ClusterRole/ingress-nginx`** (manifest)
- **`ClusterRoleBinding/ingress-nginx`** (manifest)
- **`Role/ingress-nginx`** (manifest)
- **`RoleBinding/ingress-nginx`** (manifest)
- **`IngressClass/nginx`** (manifest)

### `networking/kustomization.yaml`

- **`Kustomization/dev-lab-networking`** (manifest)

### `prometheus-stack/kustomization.yaml`

- **`Kustomization/dev-lab-prometheus-stack`** (manifest)

### `prometheus-stack/prometheus-stack.yaml`

- **`Namespace/monitoring`** (manifest)
- **`HelmRepository/prometheus-community`** (manifest)
- **`HelmRepository/grafana`** (manifest)
- **`HelmRelease/kube-prometheus-stack`** (manifest)
<!-- docgen:end id=infrastructure:reference -->
