# flagger

<!-- docgen:begin id=infrastructure/flagger:overview scope=infrastructure/flagger hash=df72478eb521 -->
This module deploys Flagger, a Kubernetes operator for GitOps-based progressive delivery. Flagger integrates with Linkerd service mesh to enable automated canary deployments. It uses Helm charts from the official Flagger repository. The module includes a CustomResourceDefinition for TrafficSplit resources from the SMI specification.

The module consists of a HelmRepository to fetch Flagger charts and a HelmRelease to install Flagger in the linkerd namespace. It configures Flagger with Linkerd integration, Prometheus metrics server, and security settings. Resource limits and requests are set for the Flagger pod. The module also enables service monitoring for Prometheus scraping.

The kustomization file ties together the HelmRelease and CRD manifests. The TrafficSplit CRD provides the SMI-based traffic splitting functionality that Flagger uses for canary deployments. The HelmRelease installs Flagger with proper namespace handling and CRD management. The module uses Flux CD to manage the Helm release lifecycle.
<!-- docgen:end id=infrastructure/flagger:overview -->

<!-- docgen:begin id=infrastructure/flagger:reference scope=infrastructure/flagger hash=df72478eb521 -->
## Reference

### `flagger.yaml`

- **`HelmRepository/flagger`** (manifest)
- **`HelmRelease/flagger`** (manifest)

### `kustomization.yaml`

- **`Kustomization/flagger`** (manifest)

### `trafficsplit-crd.yaml`

- **`CustomResourceDefinition/trafficsplits.split.smi-spec.io`** (manifest)
<!-- docgen:end id=infrastructure/flagger:reference -->
