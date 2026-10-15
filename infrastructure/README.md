# infrastructure

<!-- docgen:begin id=infrastructure:overview scope=infrastructure hash=01ec954a2c60 -->
This module defines the infrastructure for a development lab environment using Kubernetes manifests and Kustomize. It organizes components into logical groups such as base services, container registry, networking, service mesh, progressive delivery with Flagger, and monitoring. Each group uses Kustomize to manage its resources and dependencies.

The base infrastructure includes core services like metrics-server for horizontal pod autoscaling and necessary RBAC rules. The container registry provides a local Docker registry with UI access. Networking is handled by ingress-nginx controller which exposes services externally. Service mesh is implemented using Linkerd with its control plane and visualization components. Progressive delivery capabilities come from Flagger which integrates with Linkerd and Prometheus.

Monitoring stack uses Prometheus and Grafana through Helm releases. Service monitors and pod monitors are configured for Linkerd and Flagger metrics. The main kustomization file orchestrates deployment order by referencing each component group in sequence. This ensures dependencies are met before deploying components that rely on others.
<!-- docgen:end id=infrastructure:overview -->

<!-- docgen:begin id=infrastructure:reference scope=infrastructure hash=01ec954a2c60 -->
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

### `monitoring/grafana-dashboard-configmap.yaml`

- **`ConfigMap/linkerd-canary-dashboard`** (manifest)

### `monitoring/kustomization.yaml`

- **`Kustomization/dev-lab-monitoring`** (manifest)

### `monitoring/linkerd-podmonitor-simple.yaml`

- **`PodMonitor/linkerd-proxy-simple`** (manifest)

### `monitoring/linkerd-servicemonitors.yaml`

- **`ServiceMonitor/linkerd-controller`** (manifest)
- **`ServiceMonitor/linkerd-control-plane`** (manifest)
- **`PodMonitor/linkerd-proxy`** (manifest)

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

### `service-mesh/kustomization.yaml`

- **`Kustomization/dev-lab-service-mesh`** (manifest)

### `service-mesh/linkerd.yaml`

- **`HelmRepository/linkerd`** (manifest)
- **`Namespace/linkerd`** (manifest)
- **`Namespace/linkerd-viz`** (manifest)
- **`GitRepository/gateway-api`** (manifest)
- **`Kustomization/gateway-api-crds`** (manifest)
- **`HelmRelease/linkerd-crds`** (manifest)
- **`HelmRelease/linkerd-control-plane`** (manifest)
- **`HelmRelease/linkerd-viz`** (manifest)
- **`CustomResourceDefinition/trafficsplits.split.smi-spec.io`** (manifest)
<!-- docgen:end id=infrastructure:reference -->
