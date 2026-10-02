# flagger

<!-- docgen:begin id=infrastructure/flagger:overview scope=infrastructure/flagger hash=c6feb9e984e0 -->
This module manages the deployment and configuration of Flagger, a Kubernetes operator for GitOps-based progressive delivery. It integrates with Linkerd service mesh and uses Helm charts for installation, defining both the HelmRepository for fetching the chart and the HelmRelease for deploying it into the `linkerd` namespace. The configuration includes resource limits, security settings, and Prometheus integration for monitoring.

The module relies on a CustomResourceDefinition (CRD) for TrafficSplit, which is part of the Service Mesh Interface (SMI) specification. This CRD enables Flagger to manage traffic splitting across different versions of services during canary deployments. The TrafficSplit CRD is defined in a separate manifest and is installed as part of the overall Flagger setup.

The module's structure follows a Kustomization approach that combines the HelmRepository, HelmRelease, and TrafficSplit CRD into a single deployable unit. This allows for consistent deployment of Flagger along with its required CRD dependencies through Flux CD's declarative management, ensuring that all necessary components are applied together in the correct order.
<!-- docgen:end id=infrastructure/flagger:overview -->

<!-- docgen:begin id=infrastructure/flagger:reference scope=infrastructure/flagger hash=c6feb9e984e0 -->
## Reference

### `flagger.yaml`

- **`HelmRepository/flagger`** (manifest)
- **`HelmRelease/flagger`** (manifest)

### `kustomization.yaml`

- **`Kustomization/flagger`** (manifest)

### `trafficsplit-crd.yaml`

- **`CustomResourceDefinition/trafficsplits.split.smi-spec.io`** (manifest)
<!-- docgen:end id=infrastructure/flagger:reference -->
