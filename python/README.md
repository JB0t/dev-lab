# Dev Lab - Platform-Agnostic Kubernetes Development Environment

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

1. Builds `devlab-kind:latest` from `Dockerfile.kind`
2. Builds `devlab-helm:latest` from `Dockerfile.helm` with the local CA bundle
3. Builds `devlab-kubectl:latest` from `Dockerfile.kubectl` with krew and the local CA bundle
4. Uses these images for KinD, Helm, and kubectl operations

### Kubernetes Version Selection

When creating a new cluster, `devlab bootstrap` checks the published
`kindest/node` images and offers the newest patch release for each Kubernetes
minor version. Use `fzf` to select a version, or keep the configured image.
Without `fzf`, the same choices are available through a numbered prompt.

### Network CA Certificates

If your network performs TLS inspection, place its trusted root certificate(s)
anywhere under `python/certs/` before building. All nested `.crt` files are
loaded recursively and trusted automatically by the local tool image. During
bootstrap they are also installed into every KinD node so containerd can pull
images for future charts and workloads. The directory is ignored by Git so
organization-specific certificates are not committed.

### Manual Build (Optional)

You can also build the KinD image manually:

```bash
cd python/
docker build --build-arg KIND_VERSION=<configured-kind-version> --build-arg TARGETARCH=<docker-architecture> -f Dockerfile.kind -t devlab-kind:latest .
```

### KinD Image Components

The `devlab-kind:latest` image contains:

- **Base**: Alpine Linux (minimal, secure)
- **Dependencies**: curl, docker-cli
- **KinD Binary**: Downloaded from the version configured in `python/devlab.py`
- **Docker Access**: Can manage Docker containers via mounted socket
- **Networking**: Configured for container-to-container communication

### Dockerfile.kind Reference

```dockerfile
FROM alpine:latest

# Install dependencies
RUN apk add --no-cache curl docker-cli

# Install KinD
ARG KIND_VERSION
ARG TARGETARCH
RUN curl -Lo ./kind https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${TARGETARCH} && \
    chmod +x ./kind && \
    mv ./kind /usr/local/bin/kind

# Set entrypoint
ENTRYPOINT ["kind"]
```

## Container Architecture

### Kubeconfig Sharing Solution

**Problem**: KinD creates kubeconfig with `127.0.0.1:6443`, but containers can't reach each other's localhost.

**Solution**: Automatic IP address translation

1. **KinD creates cluster**: Writes kubeconfig to shared `.kube/` directory
2. **Detect container IP**: Find KinD control plane IP on `kind` network (e.g., `172.18.0.3`)
3. **Update kubeconfig**: Replace `127.0.0.1:6443` with `172.18.0.3:6443`
4. **Enable containers**: All tools can now communicate with the cluster

### Tool Container Configuration

All Kubernetes tools run with:

- **Network**: `--network kind` (access to KinD cluster)
- **Kubeconfig**: Shared directory at `/root/.kube`
- **Workspace**: Project files at `/workspace`
- **Tool-specific flags**: Context and kubeconfig parameters

### Container Images

| Tool | Image | Notes |
|------|--------|-------|
| kubectl | `devlab-kubectl:latest` | Built locally from `alpine/kubectl` with krew and the local CA bundle |
| helm | `devlab-helm:latest` | Built locally from `alpine/helm` with the local CA bundle |
| linkerd | `cr.l5d.io/linkerd/cli-bin:stable-2.14.5` | Official Linkerd registry |
| flux | `fluxcd/flux-cli:v2.3.0` | Official Flux registry |
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
python3 setup.py
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

- Create a KinD cluster with 3 nodes (1 control-plane + 2 workers)
- Install custom CA certificates from `certs/` into the nodes
- Set up the local container registry
- Install the metrics server
- Install the Traefik ingress controller
- Deploy the kube-prometheus-stack monitoring stack (Prometheus, Grafana, Alertmanager)
- Install the default krew plugins
- Show the access points

It does not install Gateway API CRDs or Linkerd. `./devlab deploy-gitops` can
optionally manage further components through Flux.

### 3. Access Services

Services are reached through Traefik on host ports 80/443 by hostname.
Browsers and `curl` resolve `*.localhost` to the loopback address, so no
`/etc/hosts` entries are needed:

- Grafana: <http://grafana.localhost> (admin / admin123)
- Prometheus: <http://prometheus.localhost>
- Alertmanager: <http://alertmanager.localhost>
- Registry UI: <http://registry.localhost>
- Traefik dashboard: <http://traefik.localhost/dashboard/>
- Registry API: <http://localhost:5000>

`./devlab kubectl port-forward` publishes the forwarded ports on the host:

```bash
./devlab kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
# Access: http://localhost:9093
```

See [NETWORKING.md](../NETWORKING.md) for details.

### 4. Check Status

```bash
./devlab status
```

### 5. Use Kubernetes Tools

```bash
# All tools run in containers automatically
./devlab kubectl get pods -A
./devlab helm list -A
./devlab linkerd check
```

After setup the wrapper is also available as `devlab` if you add `python/` to
your `PATH` (see the root README).

### 6. Clean Up

```bash
./devlab cleanup
```

## Available Commands

| Command | Description |
|---------|-------------|
| `./devlab bootstrap` | Create cluster and setup core services |
| `./devlab deploy-gitops` | Optional: deploy using the GitOps method (Flux) |
| `./devlab status` | Show cluster and service status |
| `./devlab kubectl <args>` | Run kubectl commands |
| `./devlab helm <args>` | Run helm commands |
| `./devlab linkerd <args>` | Run linkerd commands |
| `./devlab flux <args>` | Run flux commands |
| `./devlab kind <args>` | Run kind commands |
| `./devlab build -t <name[:tag]> [--push] [docker build args]` | Build `localhost:5000/<name>` for the local registry |
| `./devlab push <name[:tag]>...` | Tag (if needed) and push images to `localhost:5000` |
| `./devlab krew-sync` | Install the default krew plugins |
| `./devlab addon list` | List optional addons and whether they are installed |
| `./devlab addon enable\|disable <name>...` | Install or remove addons: `keda`, `node-autoscaler` ([AUTOSCALING.md](../AUTOSCALING.md)) |
| `./devlab completion bash [--kubectl-alias k]` | Print Bash completion, optionally for a kubectl alias |
| `./devlab build-tools` | Build the local tool images |
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
│   ├── addons/                     # Optional addons (keda, node-autoscaler)
│   ├── ingress/                    # Traefik ingress configuration
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

- **kubectl**: `devlab-kubectl:latest` (built from `Dockerfile.kubectl`)
- **helm**: `devlab-helm:latest` (built from `Dockerfile.helm`)
- **linkerd**: `cr.l5d.io/linkerd/cli-bin:stable-2.14.5`
- **kind**: host `kind` binary if installed, otherwise `devlab-kind:latest`; nodes default to `kindest/node:v1.35.8` (selected at bootstrap with KinD's `--image` option)
- **flux**: `fluxcd/flux-cli:v2.3.0`

### Volume Mounts

- Kubeconfig: shared `.kube/` directory at the repository root
- Docker socket: `/var/run/docker.sock` (for kind)
- Project files: `/workspace`

### Benefits

- **Consistent versions** across all platforms
- **No local installation** required
- **Easy updates** - just change container tags
- **Isolation** - no conflicts with existing tools
- **Security** - containers provide sandboxing

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
- `config/ingress/traefik-values.yaml` - Traefik ingress Helm values
- `config/registry/registry.yaml` - Container registry
- `config/registry/registry-ui.yaml` - Container registry UI
- `config/addons/keda/values.yaml` - KEDA Helm values
- `config/addons/node-autoscaler/` - cluster-autoscaler Helm values and KWOK node pool templates
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
   Error: Port 5000, 80, or 443 already in use
   Solution: Stop conflicting services or change ports in kind-config.yaml
   ```

### Debug Commands

```bash
# Check Docker connectivity
docker info

# Check cluster status
./devlab kubectl cluster-info

# Check all pods
./devlab kubectl get pods -A

# Check Linkerd
./devlab linkerd check
```

## Future Enhancements

- **Multiple Clusters**: Support for multiple cluster profiles
- **Template Engine**: Jinja2 templates for configuration
- **Testing Framework**: Automated testing of deployments
- **Monitoring Dashboard**: Web UI for cluster status
- **CI/CD Integration**: GitHub Actions/GitLab CI templates
