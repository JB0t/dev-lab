# gitops

<!-- docgen:begin id=config/gitops:overview scope=config/gitops hash=72b428264bf9 -->
This module defines `GitRepository` resources for use with Flux CD, configuring how Git repositories are sourced for continuous delivery. It includes two main Git repository definitions: one for a development lab repository and another for a service mesh layer repository, both targeting the `flux-system` namespace.

The `GitRepository` resources specify the Git repository URL, authentication via secret references, sync interval, and branch references. Each repository also includes ignore patterns to exclude non-Kubernetes files and directories from the sync process, ensuring only relevant manifests are processed.

These Git repository definitions are used by Flux CD to continuously sync the specified Git repositories into the Kubernetes cluster, enabling GitOps-based deployment workflows. The configuration supports different branches and namespaces, allowing for separation of concerns between different deployment layers and environments.
<!-- docgen:end id=config/gitops:overview -->

<!-- docgen:begin id=config/gitops:reference scope=config/gitops hash=72b428264bf9 -->
## Reference

### `git-repository.yaml`

- **`GitRepository/dev-lab-repo`** (manifest)

### `service-mesh-layer-gitrepository.yaml`

- **`GitRepository/flux-service-mesh-layer`** (manifest)
<!-- docgen:end id=config/gitops:reference -->
