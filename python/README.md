# Dev Lab - Platform-Agnostic Kubernetes Development Environment

<!-- docgen:begin id=python:overview scope=python hash=38cac368cdc4 -->
This module provides a platform-agnostic development environment for Kubernetes using containerized tools. It runs kubectl, helm, kind, linkerd, and flux commands inside containers to avoid local tool installation. The system uses Docker as the only requirement and creates wrapper scripts to manage the Python virtual environment.

The core components include `DevLabManager` for high-level operations like bootstrapping and deployment, and `ContainerToolRunner` for executing commands in containers. The `DevLabError` exception handles operational failures. Setup script `setup.py` manages virtual environment creation and dependency installation.

The `devlab.py` module exposes CLI functions for bootstrap, deploy, status, cleanup, and direct tool execution. It supports both traditional script-based deployment and GitOps with Flux CD. The system works across platforms by running tools in containers and provides wrapper scripts for easy command access.
<!-- docgen:end id=python:overview -->

A Python-based, platform-agnostic replacement for bash scripts that provides a complete Kubernetes development environment using only Docker as a dependency.

## Key Features

- **Platform-Agnostic**: Works on Windows, macOS, and Linux
- **Container-Based Tools**: All Kubernetes tools run in containers
- **Zero Local Installation**: Only Docker required
- **Clean Python Code**: Maintainable alternative to bash scripts
- **Rich CLI Interface**: Beautiful terminal output with progress indicators
- **Automatic kubeconfig sharing**: Seamless communication between containerized tools

## One-Time Setup: Local KinD Docker Image

The devlab tool automatically builds a local KinD container image when needed. This provides platform independence and ensures consistent behavior.

### Automatic Build (Recommended)

The KinD container image is built automatically when:

- KinD is not found on the host system
- The local `devlab-kind:latest` image doesn't exist

**Build Process:**

1. Creates `Dockerfile.kind` with Alpine Linux + curl + docker-cli + KinD binary
2. Builds the image as `devlab-kind:latest`
3. Uses this image for all KinD operations

### Manual Build (Optional)

You can also build the KinD image manually:

```bash
cd python/
docker build -f Dockerfile.kind -t devlab-kind:latest .
```

### KinD Image Components

The `devlab-kind:latest` image contains:

- **Base**: Alpine Linux (minimal, secure)
- **Dependencies**: curl, docker-cli
- **KinD Binary**: Downloaded from GitHub releases (v0.20.0)
- **Docker Access**: Can manage Docker containers via mounted socket
- **Networking**: Configured for container-to-container communication

### Dockerfile.kind Reference

```dockerfile
FROM alpine:latest

# Install dependencies
RUN apk add --no-cache curl docker-cli

# Install KinD
RUN curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64 && \
    chmod +x ./kind && \
    mv ./kind /usr/local/bin/kind

# Set entrypoint
ENTRYPOINT ["kind"]
```

## Container Architecture

### Kubeconfig Sharing Solution

**Problem**: KinD creates kubeconfig with `127.0.0.1:6443`, but containers can't reach each other's localhost.

**Solution**: Stable Docker DNS endpoint with automatic kubeconfig migration

1. **KinD creates cluster**: Writes kubeconfig to shared `.kube/` directory
2. **Update kubeconfig**: Set the `kind-dev-lab` server to `https://dev-lab-control-plane:6443`
3. **Resolve dynamically**: Docker DNS on the `kind` network resolves the control-plane name to its current IP, including after Docker or WSL restarts
4. **Migrate automatically**: Before kubectl, Helm, Linkerd, or Flux runs, devlab repairs older numeric-IP or localhost endpoints in the shared kubeconfig

Only the `kind-dev-lab` cluster's server entry is changed. Credentials, contexts,
other clusters, and the original user kubeconfig remain untouched. An already
correct shared kubeconfig is not rewritten, and TLS verification remains enabled.
No cluster recreation or bootstrap is needed: run `devlab kubectl get nodes` to
migrate an existing shared config. This fixes endpoint changes, not an API server
that is still starting or unhealthy.

### Tool Container Configuration

All Kubernetes tools run with:

- **Network**: `--network kind` (access to KinD cluster)
- **Kubeconfig**: Shared directory at `/root/.kube`
- **Workspace**: Project files at `/workspace`
- **Tool-specific flags**: Context and kubeconfig parameters

### Container Images

| Tool | Image | Notes |
|------|--------|-------|
| kubectl | `alpine/kubectl:latest` | Official Alpine-based |
| helm | `alpine/helm:latest` | Official Alpine-based |
| linkerd | `cr.l5d.io/linkerd/cli-bin:stable-2.14.5` | Official Linkerd registry |
| flux | `fluxcd/flux-cli:latest` | Official Flux registry |
| kind | `devlab-kind:latest` | Built locally |

- **Virtual Environment**: Isolated Python dependencies

## Prerequisites

1. **Docker** - Must be installed and running
2. **Python 3.8+** - Usually pre-installed on most systems

That's it! No kubectl, helm, kind, or other Kubernetes tools needed.

## Quick Start

### 1. Setup (One-time)

```bash
cd dev-lab/python
python setup.py
```

This will:

- Create a Python virtual environment
- Install required Python packages
- Create platform-specific wrapper scripts
- Verify Docker is working

### 2. Bootstrap Environment

```bash
./devlab bootstrap
```

This will:

- Create a KinD cluster with 3 nodes
- Install Linkerd service mesh
- Setup local container registry
- Install metrics server

### 3. Deploy Applications

```bash
./devlab deploy
```

This will:

- Install NGINX Ingress Controller
- Deploy Prometheus monitoring stack
- Deploy sample applications
- Show access information

### 4. Check Status

```bash
./devlab status
```

### 5. Use Kubernetes Tools

```bash
# All tools run in containers automatically
./devlab kubectl -- get pods -A
./devlab helm -- list -A
./devlab linkerd -- check
```

### 6. Clean Up

```bash
./devlab cleanup
```

## Available Commands

| Command | Description |
|---------|-------------|
| `./devlab bootstrap` | Create cluster and setup core services |
| `./devlab deploy` | Deploy applications (traditional method) |
| `./devlab status` | Show cluster and service status |
| `./devlab kubectl -- <args>` | Run kubectl commands |
| `./devlab helm -- <args>` | Run helm commands |
| `./devlab linkerd -- <args>` | Run linkerd commands |
| `./devlab cleanup` | Delete entire environment |

## Project Structure

```text
dev-lab/
├── python/                          # Python-based tools
│   ├── devlab.py                   # Main CLI application
│   ├── setup.py                    # Environment setup script
│   ├── requirements.txt            # Python dependencies
│   ├── devlab                      # Unix wrapper script (created by setup)
│   ├── devlab.bat                  # Windows wrapper script (created by setup)
│   └── venv/                       # Python virtual environment (created by setup)
├── config/                          # External configuration files
│   ├── apps/                       # Application manifests
│   ├── monitoring/                 # Monitoring configuration
│   ├── registry/                   # Container registry setup
│   └── gitops/                     # GitOps configuration
├── cluster/                         # Cluster configuration
│   └── kind-config.yaml            # KinD cluster configuration
└── scripts/                         # Original bash scripts (deprecated)
```

## Container-Based Architecture

Instead of requiring local tool installation, all Kubernetes tools run in containers:

### Tool Containers Used

- **kubectl**: `bitnami/kubectl:v1.28.3`
- **helm**: `alpine/helm:v3.13.1`
- **linkerd**: `linkerd/cli-bin:stable-2.14.5`
- **kind**: `kindest/node:v0.20.0`
- **flux**: `fluxcd/flux-cli:v2.1.2`

### Volume Mounts

- Kubeconfig: `~/.kube/config`
- Docker socket: `/var/run/docker.sock` (for kind)
- Project files: `/workspace`

### Benefits

- ✅ **Consistent versions** across all platforms
- ✅ **No local installation** required
- ✅ **Easy updates** - just change container tags
- ✅ **Isolation** - no conflicts with existing tools
- ✅ **Security** - containers provide sandboxing

## Technical Details

### Python Dependencies

- **click**: Command-line interface framework
- **docker**: Docker API client
- **PyYAML**: YAML processing
- **rich**: Beautiful terminal output

### Error Handling

- Comprehensive error checking at each step
- Clear error messages with suggestions
- Graceful failure handling
- Progress indicators for long operations

### Cross-Platform Compatibility

- Automatic platform detection
- Platform-specific wrapper scripts
- Path handling for Windows/Unix
- Docker socket mounting

## Configuration

All configuration files remain in the `config/` directory:

### External Configuration Files

- `config/monitoring/prometheus-values.yaml` - Prometheus Helm values
- `config/registry/registry-daemonset.yaml` - Container registry
- `config/apps/sample-web-app.yaml` - Sample applications
- `cluster/kind-config.yaml` - KinD cluster configuration

### Environment Variables

- `DOCKER_HOST` - Docker daemon connection (if needed)
- `KUBECONFIG` - Kubernetes configuration file path

## Troubleshooting

### Common Issues

1. **Docker not running**

   ```
   Error: Docker daemon is not running
   Solution: Start Docker Desktop or Docker daemon
   ```

1. **Permission issues on Linux**

   ```
   Error: Permission denied accessing Docker socket
   Solution: Add user to docker group: sudo usermod -aG docker $USER
   ```

1. **Python version too old**

   ```
   Error: Python 3.8 or higher is required
   Solution: Update Python or use pyenv
   ```

1. **Port conflicts**

   ```
   Error: Port 5000 already in use
   Solution: Stop conflicting services or change ports in kind-config.yaml
   ```

### Debug Commands

```bash
# Check Docker connectivity
docker info

# Check cluster status
./devlab kubectl -- cluster-info

# Check all pods
./devlab kubectl -- get pods -A

# Check Linkerd
./devlab linkerd -- check
```

## Future Enhancements

- **GitOps Support**: Add Flux CD deployment method
- **Multiple Clusters**: Support for multiple cluster profiles
- **Template Engine**: Jinja2 templates for configuration
- **Testing Framework**: Automated testing of deployments
- **Monitoring Dashboard**: Web UI for cluster status
- **Plugin System**: Extensible plugin architecture
- **CI/CD Integration**: GitHub Actions/GitLab CI templates

<!-- docgen:begin id=python:reference scope=python hash=38cac368cdc4 -->
## Reference

### `devlab.py`

- **`DevLabError`** (class): Custom exception for dev-lab operations
- **`ContainerToolRunner`** (class): Runs Kubernetes tools in containers for platform independence
- **`ContainerToolRunner.__init__`** (method)
- **`ContainerToolRunner.kubectl`** (method): Run kubectl in container
- **`ContainerToolRunner.helm`** (method): Run helm in container
- **`ContainerToolRunner.kind`** (method): Run kind CLI - try host first, then local container image as fallback
- **`ContainerToolRunner.linkerd`** (method): Run linkerd CLI in container
- **`ContainerToolRunner.flux`** (method): Run flux CLI in container
- **`DevLabManager`** (class): Main class for managing dev-lab operations
- **`DevLabManager.__init__`** (method)
- **`DevLabManager.setup_logging`** (method): Configure logging
- **`DevLabManager.check_docker`** (method): Check if Docker is available and running
- **`DevLabManager.bootstrap`** (method): Bootstrap the complete dev-lab environment
- **`DevLabManager.deploy_traditional`** (method): Deploy using traditional script-based method
- **`DevLabManager.deploy_gitops`** (method): Deploy using GitOps method with Flux CD
- **`cli`** (function): Dev Lab - Platform-Agnostic Kubernetes Development Environment
- **`bootstrap`** (function): Bootstrap the dev-lab environment
- **`deploy_traditional`** (function): Deploy using traditional method
- **`deploy_gitops`** (function): Deploy using GitOps method with Flux CD
- **`deploy`** (function): Deploy using traditional method (default)
- **`kubectl`** (function): Run kubectl commands
- **`helm`** (function): Run helm commands
- **`linkerd`** (function): Run linkerd commands
- **`flux`** (function): Run flux commands
- **`status`** (function): Show cluster and service status
- **`build_tools`** (function): Build/rebuild local tool container images
- **`cleanup`** (function): Clean up the dev-lab environment

### `setup.py`

- **`run_command`** (function): Run a command with error handling
- **`check_python`** (function): Check Python version
- **`check_docker`** (function): Check if Docker is available
- **`setup_venv`** (function): Set up Python virtual environment
- **`create_wrapper_scripts`** (function): Create platform-specific wrapper scripts
- **`show_usage_instructions`** (function): Show usage instructions
- **`main`** (function): Main setup function
<!-- docgen:end id=python:reference -->
