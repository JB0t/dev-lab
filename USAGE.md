# devlab

<!-- docgen:begin id=cli:devlab:usage scope=python hash=a192c1202f52 -->
## Usage

| Command | Description | Flags |
|---|---|---|
| `devlab addon` | Enable or disable optional components (see AUTOSCALING.md) |  |
| `devlab addon disable` | Uninstall addons |  |
| `devlab addon enable` | Install addons (safe to re-run; upgrades in place) |  |
| `devlab addon list` | List addons and whether they are installed |  |
| `devlab bootstrap` | Bootstrap the dev-lab environment | `--monitoring` `--no-monitoring` `--krew` `--no-krew` |
| `devlab build` | Build an image for the local registry (extra args go to... | `-t` `--tag` `--push` |
| `devlab build-tools` | Build/rebuild local tool container images |  |
| `devlab cleanup` | Clean up the dev-lab environment |  |
| `devlab completion` | Print a shell completion script | `--kubectl-alias` |
| `devlab deploy-gitops` | Deploy using GitOps method with Flux CD |  |
| `devlab flux ...` | Runs `flux` with the given arguments (see `flux --help`) | |
| `devlab helm ...` | Runs `helm` with the given arguments (see `helm --help`) | |
| `devlab kind ...` | Runs `kind` with the given arguments (see `kind --help`) | |
| `devlab krew-sync` | Install the default krew plugins into the containerized... |  |
| `devlab kubectl ...` | Runs `kubectl` with the given arguments (see `kubectl --help`) | |
| `devlab linkerd ...` | Runs `linkerd` with the given arguments (see `linkerd --help`) | |
| `devlab push` | Push local images to the dev-lab registry at localhost:5000 |  |
| `devlab status` | Show cluster and service status |  |

Global flags: `--profile`

### Examples

### `devlab addon disable`

Disable Kubernetes addons like KEDA or node autoscaler in your development environment.

```bash
# Disable KEDA addon
devlab addon disable keda

# Disable node autoscaler addon
devlab addon disable node-autoscaler

# Disable multiple addons at once
devlab addon disable keda node-autoscaler
```

### `devlab addon enable`

Enable specific addons in the dev-lab environment.
```bash
# Enable the keda addon
devlab addon enable keda

# Enable both keda and node-autoscaler addons
devlab addon enable keda node-autoscaler

# Enable the node-autoscaler addon
devlab addon enable node-autoscaler
```

### `devlab addon list`

List all available addons and their installation status.
```bash
# Show the list of addons
devlab addon list
```

### `devlab bootstrap`

Initialize the dev-lab environment with monitoring and krew plugins.
```bash
# Bootstrap with monitoring and krew plugins enabled
devlab bootstrap

# Bootstrap without monitoring and krew plugins
devlab bootstrap --no-monitoring --no-krew

# Bootstrap with monitoring enabled and krew plugins disabled
devlab bootstrap --monitoring --no-krew
```

### `devlab build`

Build a Docker image for the local registry.
```bash
# Build an image with a specific tag
devlab build -t myapp:latest

# Build and push an image to the local registry
devlab build -t myapp:latest --push

# Build an image with additional docker build arguments
devlab build -t myapp:latest --push -- --no-cache
```

### `devlab build-tools`

Rebuild all local tool container images.
```bash
# Rebuild all local tool container images
devlab build-tools
```

### `devlab cleanup`

Clean up the dev-lab environment to remove unused resources and clear temporary files.

```bash
# Clean up the entire dev-lab environment
devlab cleanup
```

### `devlab completion`

Use this command to generate shell completion scripts for your current shell.
```bash
devlab completion bash
```

### `devlab deploy-gitops`

Use this command to deploy your application using the GitOps methodology with Flux CD.
```bash
devlab deploy-gitops
```

### `devlab flux`

Use this tool to assemble Kubernetes CD pipelines using the GitOps approach with Flux.

```bash
# Check prerequisites before installing Flux
devlab flux check --pre

# Install Flux on a cluster
devlab flux install

# Create a Git repository source for a microservice
devlab flux create source git backend-service \
  --url=https://github.com/mycompany/backend \
  --branch=main \
  --interval=3m
```

### `devlab helm`

Use this command to interact with Helm charts and Kubernetes releases within the devlab environment.

```bash
# Install a Helm chart for a new release
devlab helm install my-release ./my-chart

# List all Helm releases in the default namespace
devlab helm list

# Upgrade an existing release with new values
devlab helm upgrade my-release ./my-chart --set image.tag=2.0.0
```

### `devlab kind`

Create and manage local Kubernetes clusters for development and testing.

```bash
# Create a new Kubernetes cluster named "my-cluster"
devlab kind create cluster --name my-cluster

# Export the kubeconfig for the "my-cluster" cluster
devlab kind export kubeconfig --name my-cluster

# Delete the "my-cluster" cluster
devlab kind delete cluster --name my-cluster
```

### `devlab krew-sync`

Use this command to install default krew plugins into the containerized kubectl environment.

```bash
# Install default krew plugins in the devlab environment
devlab krew-sync
```

### `devlab kubectl`

Use this command to manage your Kubernetes cluster, including creating, getting, and deleting resources.
```bash
# Get all pods in the default namespace
devlab kubectl get pods

# Create a new deployment from a YAML file
devlab kubectl create -f deployment.yaml

# Delete a service by name
devlab kubectl delete service my-service
```

### `devlab linkerd`

Use this command to manage the Linkerd service mesh, including installing, checking, and upgrading the control plane.
```bash
# Check the Linkerd installation for potential problems
devlab linkerd check

# Install Linkerd with default settings
devlab linkerd install

# Upgrade an existing Linkerd control plane
devlab linkerd upgrade
```

### `devlab push`

Use this command to push local Docker images to the dev-lab registry for testing.
```bash
# Push a single image to the registry
devlab push my-app:latest

# Push multiple images to the registry
devlab push my-app:latest another-app:v1.0

# Push an image with a specific tag
devlab push my-app:v1.2.3
```

### `devlab status`

Use this command to check the current status of the cluster and services in the dev-lab environment.
```bash
# Show the overall status of the cluster
devlab status
```
<!-- docgen:end id=cli:devlab:usage -->
