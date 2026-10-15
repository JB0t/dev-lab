# service-mesh

<!-- docgen:begin id=infrastructure/service-mesh:overview scope=infrastructure/service-mesh hash=94b4bbbf5e96 -->
This module installs and configures the Linkerd service mesh in a Kubernetes cluster using Flux CD. It defines the necessary Kubernetes resources and Helm releases to deploy Linkerd control plane, Viz extension, and required CRDs. The setup uses Helm repositories and Git repositories to manage versions and updates.

The module consists of multiple manifests that work together to bootstrap Linkerd. It creates dedicated namespaces for the control plane and Viz extension. It installs Linkerd CRDs first, then the control plane with specific resource limits and configuration for the development environment. The Viz extension provides monitoring and visualization capabilities.

The manifests use Flux CD controllers to manage the deployment lifecycle. HelmRelease resources handle the installation and upgrades of Linkerd components. CustomResourceDefinition defines the TrafficSplit resource needed for SMI compatibility. The module relies on standard Kubernetes and Flux CRDs to orchestrate the service mesh installation.
<!-- docgen:end id=infrastructure/service-mesh:overview -->

<!-- docgen:begin id=infrastructure/service-mesh:reference scope=infrastructure/service-mesh hash=94b4bbbf5e96 -->
## Reference

### `kustomization.yaml`

- **`Kustomization/dev-lab-service-mesh`** (manifest)

### `linkerd.yaml`

- **`HelmRepository/linkerd`** (manifest)
- **`Namespace/linkerd`** (manifest)
- **`Namespace/linkerd-viz`** (manifest)
- **`GitRepository/gateway-api`** (manifest)
- **`Kustomization/gateway-api-crds`** (manifest)
- **`HelmRelease/linkerd-crds`** (manifest)
- **`HelmRelease/linkerd-control-plane`** (manifest)
- **`HelmRelease/linkerd-viz`** (manifest)
- **`CustomResourceDefinition/trafficsplits.split.smi-spec.io`** (manifest)
<!-- docgen:end id=infrastructure/service-mesh:reference -->
