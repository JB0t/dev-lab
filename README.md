# Local Kubernetes Development Lab

![Version](https://img.shields.io/badge/Version-v0.5.1-blue)

A comprehensive local development environment with **dual deployment options**: traditional script-based or modern GitOps-based, now featuring a **platform-agnostic Python CLI**.

> **For GitOps setup guide, see [GITOPS-GUIDE.md](./GITOPS-GUIDE.md)**

## Features

- **Platform Agnostic**: Python CLI with Docker-only dependency (works on Windows, macOS, Linux)
- **High Availability Kubernetes Cluster**: 3-node KinD cluster (1 control-plane + 2 workers)
- **GitOps with Flux CD**: Complete Flux v2 setup with source/kustomize/helm/notification controllers
- **Service Mesh Testing**: Complete Linkerd service mesh with canary deployments and mTLS
- **Monitoring Stack**: Lightweight Prometheus, Grafana, and AlertManager
- **Local Container Registry**: Docker registry accessible at localhost:5000
- **Ingress Controller**: Traefik ingress on host ports 80/443, with services reached by `*.localhost` hostnames
- **Metrics Server**: For cluster autoscaling and resource monitoring
- **Container-based Tools**: All Kubernetes tools run in containers (no local installation needed)

## Pre-requisites

### Runtime Environment

- **Bash**: Recommended for the smoothest experience and required by the legacy scripts.
- **Linux, macOS, or Windows with WSL2**: On Windows, run the Bash commands from a WSL2 distribution. WSL2 must be able to reach the Docker daemon.
- **Docker daemon**: Must be installed, running, and usable by your current user. Docker Desktop with WSL integration or Docker installed directly in WSL both work.
- **Network access**: Required during setup to download Python packages, container images, Kubernetes manifests, Helm charts, and KinD node images.
- **Trusted CA certificates**: Required when your network performs TLS inspection. Place trusted `.crt` files under `python/certs/`; nested directories are supported. Bootstrap installs them into the KinD nodes so containerd can pull arbitrary images for future workloads.

### Required Packages

For the recommended Python CLI:

- **Python 3.8 or newer** with `venv` and `pip` support. `python/setup.py` installs the Python dependencies listed in `python/requirements.txt`.
- **Docker CLI and daemon**. The CLI uses Docker to run `kubectl`, Helm, Flux, and Linkerd containers, and to create the KinD cluster.
- **Git** for working with this repository and for GitOps workflows.

For the legacy Bash scripts, install these on the host as well:

- **`kubectl`**
- **Helm**
- **KinD**
- **`jq`**
- **`curl`**
- **OpenSSH tools**, including `ssh-keygen`, for Flux deploy keys

### Optional Additions

- **`fzf`**: Used by `devlab bootstrap` to choose the newest KinD node patch for each Kubernetes minor version. Without it, bootstrap provides a numbered prompt.
- **Linkerd CLI**: Needed only for workflows that explicitly install or operate Linkerd through the legacy scripts; the Python CLI runs its Linkerd commands in a container.
- **Flux CLI**: Needed only for legacy scripts; the Python CLI runs Flux in a container.
- **Host `kubectl`, Helm, and KinD**: Optional with the Python CLI. Host KinD is used when available; otherwise the CLI builds and uses `devlab-kind:latest`.

## Quick Start

### Option 1: Python CLI (Recommended)

```bash
# Setup Python environment
python3 python/setup.py

# Persist the wrapper path and tab completion for future Bash sessions
# Replace ~/.bashrc with ~/.bash_profile or the startup file your Bash installation uses
DEVLAB_DIR="$(pwd)/python"
printf '\nexport PATH="$PATH:%s"\n' "$DEVLAB_DIR" >> ~/.bashrc
printf 'source <(devlab completion bash)\n' >> ~/.bashrc
source ~/.bashrc

# Build local tool container images (optional, built automatically when needed)
devlab build-tools

# Bootstrap the cluster (prints the access points when done)
devlab bootstrap

# Optional: deploy using the GitOps method
devlab deploy-gitops

# Check status
devlab status

# Use container-based tools
devlab kubectl get pods -A
devlab helm list -A
devlab linkerd check
devlab flux get all -A
devlab kind get clusters

# Optional: create aliases if you hate typing
alias kubectl='devlab kubectl'
alias helm='devlab helm'
alias linkerd='devlab linkerd'
alias flux='devlab flux'

# Cleanup when done
devlab cleanup
```

`devlab bootstrap` creates a KinD cluster (1 control-plane + 2 workers),
installs your custom CA certificates into the nodes, and installs the local
registry, metrics-server, the Traefik ingress controller, the
kube-prometheus-stack monitoring stack, and the default krew plugins. When it
finishes, these services are available:

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | <http://grafana.localhost> | admin / admin123 |
| Prometheus | <http://prometheus.localhost> | - |
| Alertmanager | <http://alertmanager.localhost> | - |
| Registry UI | <http://registry.localhost> | - |
| Traefik dashboard | <http://traefik.localhost/dashboard/> | - |
| Registry API | <http://localhost:5000> | - |

Browsers and `curl` resolve `*.localhost` to the loopback address, so no
`/etc/hosts` entries are needed. See [NETWORKING.md](./NETWORKING.md) for how
ingress and port mappings work.

### Option 2: Bash Scripts (Legacy)

```bash
# 1. Install prerequisites (if needed)
./scripts/install-prerequisites.sh

# 2. Bootstrap common infrastructure
./scripts/bootstrap.sh

# 3. Deploy either:
# via scripts
./scripts/deploy-traditional.sh
# via GitOps
./scripts/deploy-gitops.sh
```

### Test the Environment

```bash
# Run comprehensive tests
./scripts/test-environment.sh

# Manual verification
kubectl get nodes
kubectl -n monitoring get pods
curl -s http://localhost:5000/v2/_catalog
```

## Image Workflow

Build and push images to the local registry at `localhost:5000`. Nodes pull
from it through a containerd mirror, so `kind load` and
`imagePullPolicy: Never` are not needed.

```bash
# Build as localhost:5000/my-app:1 and push (extra args go to docker build)
devlab build -t my-app:1 --push .
devlab build -t my-app:1 -f docker/Dockerfile --build-arg VERSION=1 .

# Push an image you already built with plain docker build
devlab push my-app:1

# Verify in registry
curl -s http://localhost:5000/v2/_catalog
```

Reference the image as `image: localhost:5000/my-app:1` in manifests.

See [NETWORKING.md](./NETWORKING.md) for how the registry, port mappings, and
ingress are wired.

## kubectl Plugins (krew)

`devlab kubectl` runs in a local `devlab-kubectl` image that includes
[krew](https://krew.sigs.k8s.io/). Plugins live in `.krew/` at the repository
root, so they persist between runs. The default plugins (`ctx`, `gpugo`,
`neat`, `ns`, `tree`, `who-can`) install on first use of `devlab kubectl`, at
the end of `devlab bootstrap`, or with `devlab krew-sync`.

```bash
devlab kubectl ns monitoring
devlab kubectl krew install <plugin>
```

## Shell Completion for a kubectl Alias

To complete an alias of `devlab kubectl` such as `k`, pass the alias name to
setup. The option is repeatable; leave it out to skip alias completion.

```bash
python3 python/setup.py --kubectl-alias k
echo "alias k='devlab kubectl'" >> ~/.bashrc
```

This installs `~/.local/share/bash-completion/completions/k`. To turn the
alias completion off again, delete that file. A `complete ... k` line in
`~/.bashrc` overrides the installed file. When you source completion from
`~/.bashrc` instead, use `source <(devlab completion bash --kubectl-alias k)`.

`devlab kubectl exec <pod> -- <cmd>` passes the `--` through to kubectl, and
`-it` gets a TTY when you run it from a terminal. `devlab kubectl port-forward`
publishes the forwarded ports on the host, so `http://localhost:<port>` works
as with a local kubectl.

## Helm Chart Development

### Basic Workflow

```bash
# Create a new chart
helm create my-chart

# Customize values and templates
# ...

# Install from local chart
helm install my-release ./my-chart

# Upgrade after changes
helm upgrade my-release ./my-chart

# Package the chart
helm package my-chart

# Test the chart
helm test my-release
```

### Chart Testing with Built Images

```bash
# Build your app image and push it to the local registry
devlab build -t my-app:latest --push .

# Install chart with the registry image
helm install my-release ./my-chart \
  --set image.repository=localhost:5000/my-app \
  --set image.tag=latest
```

## Service Mesh Testing with Linkerd

The dev-lab includes a comprehensive service mesh testing environment with Linkerd, featuring advanced canary deployment capabilities, mTLS communication, and production-ready patterns.

### Service Mesh Features

- **Linkerd Service Mesh**: Complete setup with automatic proxy injection
- **mTLS Encryption**: Secure communication between all services
- **Canary Deployments**: Multiple deployment strategies (SMI TrafficSplit, Linkerd native HTTPRoute, header-based routing)
- **Zero-Downtime Deployments**: Proven deployment patterns with health monitoring
- **Real-time Observability**: Traffic analysis, metrics, and performance monitoring
- **Production-Ready Test App**: Node.js application with health checks, metrics, and Redis backend

### Canary Deployment Methods

`<!-- TODO: update canary tests (include flagger) -->`

#### Method 1: Linkerd Native HTTPRoute (Recommended)

The most robust approach using Linkerd's native capabilities with Gateway API:

```bash
# Progressive canary deployment (10% → 25% → 50% → 75% → 100%)
./scripts/linkerd-canary.sh progressive

# Manual traffic control
./scripts/linkerd-canary.sh httproute 80 20    # 80% v1, 20% v2
./scripts/linkerd-canary.sh httproute 50 50    # A/B testing
./scripts/linkerd-canary.sh httproute 20 80    # Heavy canary

# Automated canary with health monitoring
./scripts/linkerd-canary.sh automated 30       # 30-second intervals
```

#### Method 2: Header-Based Canary (Safest)

Route specific traffic to canary based on HTTP headers:

```bash
# Deploy header-based canary
./scripts/linkerd-canary.sh header-canary

# Test canary version
curl -H 'x-canary: true' http://mesh-test.local/

# Regular traffic goes to stable version
curl http://mesh-test.local/
```

Traffic reaches the app through the Traefik ingress on port 80. The Ingress
host must resolve to your machine: either give the Ingress a `*.localhost`
name (for example `mesh-test.localhost`) or add `127.0.0.1 mesh-test.local` to
`/etc/hosts`.

#### Method 3: SMI TrafficSplit (Traditional)

Compatible with Service Mesh Interface standards:

```bash
# Deploy with 10% canary traffic
./scripts/canary-deploy.sh deploy

# Progressive traffic shifting
./scripts/canary-deploy.sh weights 80 20   # 20% canary
./scripts/canary-deploy.sh weights 50 50   # 50/50 split
./scripts/canary-deploy.sh weights 20 80   # 80% canary

# Promote or rollback
./scripts/canary-deploy.sh promote         # 100% canary
./scripts/canary-deploy.sh rollback        # Back to stable
```

### Service Mesh Observability

#### Linkerd Dashboard

```bash
# Access Linkerd dashboard
kubectl port-forward -n linkerd-viz svc/web 8084:8084
# Visit: http://localhost:8084
```

#### Real-time Traffic Analysis

```bash
# Monitor traffic statistics
./scripts/linkerd-canary.sh monitor

# Live traffic analysis (60 seconds)
./scripts/linkerd-canary.sh analyze 60

# Check mesh health
./scripts/linkerd-canary.sh health
```

#### Command-line Monitoring

```bash
# linkerd below is the devlab linkerd alias from Quick Start
# Service statistics
linkerd viz stat deploy -n mesh-test

# Traffic distribution
linkerd viz top -n mesh-test

# Real-time request flow
linkerd viz tap -n mesh-test --to svc/mesh-test-app-service

# mTLS verification
linkerd viz edges -n mesh-test
```

### Testing Scenarios

#### Zero-Downtime Deployment Test

```bash
# Run comprehensive load test during canary deployment
./scripts/test-suite.sh 300 20 10  # 5min test, 20 RPS, 10 workers

# Monitor in separate terminal
watch kubectl get pods -n mesh-test
```

#### Service Mesh Security Testing

```bash
# Verify mTLS encryption
linkerd viz edges -n mesh-test --as table

# Test service-to-service communication
kubectl exec -n mesh-test deployment/mesh-test-app -- curl -s http://redis-service:6379
```

#### Performance Benchmarking

```bash
# High-load stress test
./scripts/test-suite.sh 600 50 20  # 10min, 50 RPS, 20 workers

# Monitor resource usage
kubectl top pods -n mesh-test
```

### Application Architecture

The mesh test application demonstrates production patterns:

```text
┌─────────────────┐    ┌─────────────────┐
│   Load Balancer │    │     Ingress     │
│    (Traefik)    │────│   Controller    │
└─────────────────┘    └─────────────────┘
                                │
                       ┌─────────────────┐
                       │   HTTPRoute/    │
                       │  TrafficSplit   │
                       │   (Linkerd)     │
                       └─────────────────┘
                         │              │
                    ┌────▼────┐    ┌────▼────┐
                    │ App v1  │    │ App v2  │
                    │(stable) │    │(canary) │
                    └────┬────┘    └────┬────┘
                         │              │
                       ┌─▼──────────────▼─┐
                       │     Redis        │
                       │   (Database)     │
                       └──────────────────┘
```

### Key Endpoints

- **Main Application**: `/` - App info with version and counter
- **Health Checks**: `/health`, `/health/live`, `/health/ready`
- **API Data**: `/api/data` - Sample data from Redis with version info
- **Metrics**: `/metrics` - Prometheus metrics endpoint
- **Load Testing**: `/api/load/:duration` - Simulate load for testing

### Production-Ready Features

- **Health Probes**: Kubernetes liveness and readiness checks
- **Graceful Shutdown**: Proper SIGTERM handling
- **Resource Limits**: CPU and memory constraints
- **Security**: mTLS encryption for all service communication
- **Observability**: Comprehensive metrics and tracing
- **Zero Downtime**: Proven deployment strategies
- **Automated Testing**: Load generation and health verification

## Monitoring Access

### Monitoring UIs

The monitoring UIs are served through the Traefik ingress:

- **Grafana**: <http://grafana.localhost> (admin / admin123)
- **Prometheus**: <http://prometheus.localhost>
- **Alertmanager**: <http://alertmanager.localhost>

For ad hoc access to other services, use a port forward. `devlab kubectl
port-forward` publishes the port on the host:

```bash
devlab kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
# Access: http://localhost:9093
```

### Get Grafana Password

```bash
kubectl get secret -n monitoring kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d ; echo
```

### Key Grafana Dashboards

- **Kubernetes / Compute Resources / Cluster**: Overall cluster metrics
- **Kubernetes / Compute Resources / Namespace (Pods)**: Pod-level metrics
- **Node Exporter / Nodes**: Node hardware metrics

## Resource Load Testing

The metrics server (installed by bootstrap) powers `kubectl top` and the
Grafana resource dashboards. Generate some CPU load and watch it:

```bash
# A busy-loop workload with a CPU request, so the scheduler accounts for it
devlab kubectl create deployment cpu-load --image=busybox:1.36 -- sh -c 'while :; do :; done'
devlab kubectl set resources deployment cpu-load --requests=cpu=100m --limits=cpu=200m

# Scale it up and watch resource use per node and per pod
devlab kubectl scale deployment cpu-load --replicas=10
watch devlab kubectl top nodes
devlab kubectl top pods

# Prometheus query: sum(rate(container_cpu_usage_seconds_total[5m])) by (pod)

# Clean up
devlab kubectl delete deployment cpu-load
```

## Directory Structure

```text
dev-lab/
├── apps/
│   └── mesh-test-app/           # Service mesh testing application
│       ├── server.js            # Node.js application with Redis integration
│       ├── package.json         # Dependencies and scripts
│       ├── Dockerfile           # Container configuration
│       ├── k8s/                 # Kubernetes manifests
│       │   ├── base.yaml        # Core app, service, ingress
│       │   ├── redis.yaml       # Redis database deployment
│       │   ├── canary.yaml      # SMI TrafficSplit canary
│       │   ├── canary-simple.yaml # Simple canary services
│       │   ├── linkerd-native-split.yaml # Linkerd native traffic splitting
│       │   ├── linkerd-httproute.yaml    # HTTPRoute-based canary
│       │   └── trafficsplit-crd.yaml     # TrafficSplit CRD
│       └── scripts/             # Automation scripts
│           ├── setup-service-mesh.sh     # Complete environment setup
│           ├── canary-deploy.sh          # SMI-based canary management
│           ├── linkerd-canary.sh         # Linkerd native canary management
│           └── test-suite.sh             # Comprehensive testing framework
├── cluster/
│   └── kind-config.yaml         # KinD cluster configuration
├── config/
│   ├── gitops/                  # Flux GitRepository configuration
│   ├── ingress/
│   │   └── traefik-values.yaml  # Traefik Helm values
│   ├── monitoring/
│   │   └── prometheus-values.yaml # kube-prometheus-stack Helm values
│   └── registry/
│       ├── registry.yaml        # Registry Deployment
│       └── registry-ui.yaml     # Registry UI
├── python/                      # devlab CLI (devlab.py, setup.py, Dockerfiles)
├── scripts/                     # Legacy Bash scripts
├── examples/
│   └── gitops-linkerd/         # GitOps + Linkerd example (git submodule)
└── README.md                   # This file
```

## Common Tasks

### Check Cluster Status

```bash
kubectl get nodes
kubectl get pods --all-namespaces
kubectl cluster-info
```

### Registry Operations

```bash
# List images in registry
curl -s http://localhost:5000/v2/_catalog

# Get tags for an image
curl -s http://localhost:5000/v2/<image-name>/tags/list

# Registry health check
curl -s http://localhost:5000/v2/
```

### Troubleshooting

#### Pods Stuck in ImagePullBackOff

- Push the image to the local registry: `devlab push <image>`
- Check the image is in the registry: `curl -s http://localhost:5000/v2/_catalog`
- Reference the image as `localhost:5000/<image>` in the manifest

#### Monitoring Stack Not Starting

- Check resource constraints: `kubectl describe pods -n monitoring`
- Verify Helm repos: `helm repo list`
- Check PVC status: `kubectl get pvc -n monitoring`

#### Registry Not Accessible

- Verify registry pod: `kubectl -n dev-lab-registry get pods`
- Check port mapping: `docker ps | grep dev-lab-control-plane`
- Test connectivity: `curl -v http://localhost:5000/v2/`

### Cleanup

```bash
# Delete the entire cluster
devlab cleanup

docker system prune -f  # Optional: clean up images
```

## Advanced Configuration

### Custom Monitoring

Edit `config/monitoring/prometheus-values.yaml` to:

- Add custom metrics endpoints
- Configure alert rules
- Adjust resource limits
- Enable additional exporters

### Registry Configuration

Edit `config/registry/registry.yaml` to:

- Change storage backend
- Add authentication
- Configure garbage collection
- Enable webhooks

### Cluster Scaling

Edit `cluster/kind-config.yaml` to:

- Add more worker nodes
- Adjust resource limits
- Configure networking
- Add extra mounts

## Versioning

This project uses **automated semantic versioning** based on branch naming conventions:

- `feature/*` → `dev` = Minor version bump
- `patch/*` → `dev` = Patch version bump
- `dev` → `main` = Major version bump

Check current version and rules:

```bash
./scripts/version-info.sh        # Show version info
./scripts/version-info.sh rules  # Show versioning rules
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed workflow guidelines.

## Performance Tips

1. **Resource Allocation**: The lightweight monitoring configuration reduces resource usage significantly
2. **Image Management**: Push images to the local registry with `devlab build --push` or `devlab push`
3. **Persistent Storage**: Registry data persists in `/tmp/dev-lab-registry` on the Docker host, so it survives a cluster recreate
4. **Service Access**: Expose services through the Traefik ingress with a `*.localhost` host, or use `devlab kubectl port-forward` for ad hoc access

## Misc

Lint markdown like this:

```bash
mkdownfix --exclude-dirs apps/mesh-test-app/node_modules
```

## License

This development lab setup is provided as-is for educational and development purposes.
