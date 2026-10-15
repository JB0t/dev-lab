# dev-lab

<!-- docgen:begin id=clusters/dev-lab:overview scope=clusters/dev-lab hash=46a99a546d31 -->
This module defines Flux `Kustomization` resources for a development lab cluster. It manages infrastructure and application deployments through GitOps. The module uses `dev-lab-repo` as the source for both infrastructure and apps paths.

The `dev-lab-infrastructure` kustomization applies Kubernetes manifests under the `./infrastructure` path. It waits for specific deployments to become healthy before considering the apply complete. The `dev-lab-apps` kustomization depends on the infrastructure kustomization. It applies manifests under the `./apps` path after infrastructure is ready.

Both kustomizations run every 10 minutes with 5 minute timeouts. They prune deleted resources and wait for successful apply. The infrastructure kustomization watches `ingress-nginx-controller` and `kube-prometheus-stack-operator` deployments for health. The apps kustomization depends on infrastructure completion before starting.
<!-- docgen:end id=clusters/dev-lab:overview -->

<!-- docgen:begin id=clusters/dev-lab:reference scope=clusters/dev-lab hash=46a99a546d31 -->
## Reference

### `dev-lab-kustomizations.yaml`

- **`Kustomization/dev-lab-infrastructure`** (manifest)
- **`Kustomization/dev-lab-apps`** (manifest)
<!-- docgen:end id=clusters/dev-lab:reference -->
