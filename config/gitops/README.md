# gitops

<!-- docgen:begin id=config/gitops:overview scope=config/gitops hash=8d8fcaf53336 -->
This module defines a GitRepository custom resource for Flux CD. It configures a source controller to sync Kubernetes manifests from a Git repository. The resource points to a specific branch and uses SSH authentication. The module manages the synchronization interval and ignores non-Kubernetes files.

The GitRepository resource uses the `source.toolkit.fluxcd.io/v1` API version. It references a secret for authentication in the `flux-system` namespace. The repository URL uses SSH protocol to connect to a GitHub repository. The configuration specifies the main branch as the source of truth.

The module integrates with Flux CD's source controller system. It provides the necessary metadata and specification for Git repository synchronization. The ignore pattern filters out documentation files and scripts not related to the cluster configuration. The resource name `dev-lab-repo` identifies this specific Git repository in the cluster.
<!-- docgen:end id=config/gitops:overview -->

<!-- docgen:begin id=config/gitops:reference scope=config/gitops hash=8d8fcaf53336 -->
## Reference

### `git-repository.yaml`

- **`GitRepository/dev-lab-repo`** (manifest)
<!-- docgen:end id=config/gitops:reference -->
