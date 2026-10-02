# dev-lab

<!-- docgen:begin id=clusters/dev-lab:overview scope=clusters/dev-lab hash=7e27d50f0636 -->
This module defines the `dev-lab` cluster configuration using Kustomize and Flux CD for declarative infrastructure management. It consists of a main `kustomization.yaml` file that references a set of Kustomization resources defined in `dev-lab-kustomizations.yaml`. These resources represent different layers of the cluster's infrastructure, from base components to applications, each managed as a separate Flux Kustomization.

The core components are organized into logical layers: base infrastructure, monitoring with Prometheus, container registry, service mesh (Linkerd), networking, progressive delivery with Flagger, and application deployments. Each Kustomization specifies its source repository, path, and health checks to ensure proper ordering and validation during deployment.

The structure uses Flux's `Kustomization` CRDs to manage the lifecycle of Kubernetes resources across multiple Git repositories and paths. The module includes health checks to validate that critical components are running correctly after deployment. The `dev-lab-kustomizations.yaml` file contains multiple Kustomization manifests with specific configurations for each layer, including `dev-lab-base`, `dev-lab-prometheus`, `dev-lab-registry`, `dev-lab-service-mesh-layer`, `dev-lab-networking`, `dev-lab-flagger`, `dev-lab-monitoring`, and `dev-lab-apps`.
<!-- docgen:end id=clusters/dev-lab:overview -->

<!-- docgen:begin id=clusters/dev-lab:reference scope=clusters/dev-lab hash=7e27d50f0636 -->
## Reference

### `dev-lab-kustomizations.yaml`

- **`Kustomization/dev-lab-base`** (manifest)
- **`Kustomization/dev-lab-prometheus`** (manifest)
- **`Kustomization/dev-lab-registry`** (manifest)
- **`Kustomization/dev-lab-service-mesh-layer`** (manifest)
- **`Kustomization/dev-lab-networking`** (manifest)
- **`Kustomization/dev-lab-flagger`** (manifest)
- **`Kustomization/dev-lab-monitoring`** (manifest)
- **`Kustomization/dev-lab-apps`** (manifest)

### `kustomization.yaml`

- **`Kustomization/`** (manifest)
<!-- docgen:end id=clusters/dev-lab:reference -->
