# Local Kubernetes Development Lab

A local Kubernetes development environment on [kind](https://kind.sigs.k8s.io/), with **two deployment options**: traditional (devlab installs everything) or GitOps (Flux deploys from this repository). It is driven by `devlab`, a single Go binary, and ships as a tarball you can copy to any Linux machine with Docker.

> **📖 For GitOps setup guide, see [GITOPS-GUIDE.md](./GITOPS-GUIDE.md)**

## Features

- **Docker is the only requirement**: `devlab` has kind built in, and the release tarball bundles `kubectl`, `helm`, `linkerd` and `flux`
- **Copy-and-run releases**: one tarball per architecture (x86_64, aarch64) with the binaries, config and guides
- **High Availability Kubernetes Cluster**: 3-node KinD cluster (1 control-plane + 2 workers)
- **GitOps with Flux CD**: Complete Flux v2 setup with source/kustomize/helm/notification controllers
- **Service Mesh Testing**: Complete Linkerd service mesh with canary deployments and mTLS
- **Monitoring Stack**: Lightweight Prometheus, Grafana, and AlertManager
- **Local Container Registry**: Docker registry accessible at localhost:5000
- **Ingress Controller**: NGINX ingress for local service exposure
- **Metrics Server**: For cluster autoscaling and resource monitoring
- **GPU-Enabled Option**: `bin/devlab bootstrap --gpu` builds the same cluster with NVIDIA GPUs on the workers, time-sliced for sharing

## Quick Start

### From a Release Tarball

Download `dev-lab_main_v<version>_<arch>.tar.gz` for your machine (`x86_64` or `aarch64`) from the [GitHub releases](https://github.com/jbotstevens/dev-lab/releases), copy it to the machine that will run the cluster, and unpack it:

```bash
tar -xzf dev-lab_main_v0.1.0_x86_64.tar.gz
cd dev-lab_main_x86_64

# Create the cluster and install Linkerd
bin/devlab bootstrap

# OR a GPU-enabled cluster (Linux + NVIDIA GPU, see below)
bin/devlab bootstrap --gpu

# Deploy using the traditional method
bin/devlab deploy-traditional

# OR using GitOps
bin/devlab deploy-gitops

# Check status, and test the whole environment
bin/devlab status
bin/devlab test

# Bundled tools, pointed at the dev-lab cluster
bin/devlab kubectl get pods -A
bin/devlab helm list -A
bin/devlab linkerd check
bin/devlab flux get all -A

# Delete the cluster when done
bin/devlab cleanup
```

The target machine needs Docker (running, and usable by your user) and internet access: kind node images and the Linkerd, monitoring and other images are pulled during bootstrap and deploy. Nothing else needs installing. Release tarballs contain:

| Path | Contents |
|------|----------|
| `bin/devlab` | dev-lab CLI (static binary, kind built in) |
| `bin/kubectl`, `bin/helm`, `bin/linkerd`, `bin/flux` | Pinned upstream CLIs (versions in `manifest.txt`) |
| `cluster/`, `config/`, `clusters/` | kind config, Helm values and Kubernetes manifests; edit them in place |
| `apps/` | Sample applications for the service mesh guides |
| `*.md` | This README and the guides |
| `licenses/` | Third-party licenses |
| `manifest.txt` | Version, branch, commit and architecture |

`devlab` finds its files relative to its own location (`<home>/bin/devlab`), so it can be run from any directory. Set `--home` or `DEVLAB_HOME` to use a different home.

### Kubeconfig

`devlab` writes the cluster's kubeconfig to `<home>/.kube/config` (context `kind-dev-lab`) and never touches `~/.kube/config`. The `bin/devlab kubectl|helm|linkerd|flux` commands use it automatically.

The rest of this README and the guides use plain `kubectl`, `helm` and `linkerd`. To run those with the bundled tools against the dev-lab cluster, from the dev-lab home:

```bash
export KUBECONFIG=$(bin/devlab kubeconfig) PATH="$PWD/bin:$PATH"
kubectl get nodes
```

### From a Checkout

The repository has the same layout as a release, so you can build and run it in place (Go from `go.mod`):

```bash
go build -o bin/devlab ./cmd/devlab
scripts/fetch-tools.sh x86_64 bin      # bundled CLIs, checksum-verified
bin/devlab bootstrap
```

`scripts/build-distribution.sh --arch all <version>` builds the release tarballs into `build/`; CI does this on every push (see [Releases](#releases)).

### Test the Environment

```bash
# Cluster, nodes, registry, monitoring, ingress, and building, loading
# and running an image
bin/devlab test

# Manual verification
bin/devlab kubectl get nodes
bin/devlab kubectl -n monitoring get pods
curl -s http://localhost:5000/v2/_catalog
```

## Commands

| Command | Does |
|---------|------|
| `bootstrap [--gpu] [--recreate]` | Create the cluster, install Gateway API CRDs and Linkerd (+ NVIDIA device plugin with `--gpu`) |
| `deploy-traditional` (alias `deploy`) | Install registry, metrics-server, NGINX ingress and the Prometheus stack |
| `deploy-gitops [--repo-url URL] [--no-prompt]` | Install Flux, create a deploy key, and deploy `infrastructure/` and `apps/` from Git |
| `status` | Docker, cluster and node status (with allocatable GPUs) |
| `test` | End-to-end check of a deployed environment |
| `load-image IMAGE... [--nodes ...]` | Load local Docker images into the cluster nodes |
| `gpu-plugin` | Reinstall the NVIDIA device plugin (applies time-slicing changes) |
| `kubeconfig` | Print the kubeconfig path |
| `kubectl`, `helm`, `linkerd`, `flux` | Run the bundled tool against the cluster (a leading `--` is optional) |
| `cleanup [-y]` | Delete the cluster |

## Releases

GitHub Actions (`.github/workflows/build.yml`) runs on every push and pull request:

1. **test**: `gofmt`, `go vet`, `go test ./...`, and the Dask sample workload tests.
2. **build**: `scripts/build-distribution.sh` builds `dev-lab_<branch>_v<version>_<arch>.tar.gz` for x86_64 and aarch64, and checks they contain no Go source. Branch builds are versioned `X.Y.Z.ci.<run>` (the next patch after the latest tag) and kept as workflow artifacts for 7 days.
3. **release**, on a `vX.Y.Z` tag only: builds at version `X.Y.Z` and attaches the tarballs to a GitHub Release, with that version's section of [CHANGELOG.md](./CHANGELOG.md) as the notes.

To release: add a `## vX.Y.Z` section to `CHANGELOG.md`, merge, then `git tag vX.Y.Z && git push origin vX.Y.Z`.

Pinned versions (bump them in one place each):

| Component | Version | Pinned in |
|-----------|---------|-----------|
| kind library / node image | v0.20.0 / Kubernetes v1.27.3 | `go.mod`, `internal/lab/lab.go` |
| kubectl, helm, linkerd, flux | v1.28.3, v3.13.1, stable-2.14.10, v2.3.0 | `scripts/fetch-tools.sh` (with SHA-256s) |
| Gateway API, metrics-server, NGINX ingress | v1.0.0, v0.7.2, v1.8.1 | `internal/lab/lab.go` |
| NVIDIA device plugin chart | 0.20.1 | `internal/lab/lab.go` |

## GPU-Enabled Cluster

`bin/devlab bootstrap --gpu` creates the same `dev-lab` cluster (same name, ports, registry and labels) with NVIDIA GPUs injected into the worker nodes, then installs the [NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin) so pods can request `nvidia.com/gpu`. Each physical GPU is [time-sliced](#gpu-time-slicing) into 4 shares by default. Everything after bootstrap (`deploy-traditional`, `deploy-gitops`, `status`, `cleanup`) works the same.

The GPU setup follows [nvkind](https://github.com/NVIDIA/nvkind): `devlab` renders the cluster from an nvkind-style template and runs nvkind's node setup itself, so nvkind, kind and kubectl are not needed on the host.

### Host Requirements

- Linux (or WSL2) with an NVIDIA GPU and driver: `nvidia-smi -L` lists your GPUs
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

Configure Docker so GPUs can be injected into the kind node containers (one-time):

```bash
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default --cdi.enabled
sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place
sudo systemctl restart docker

# Verify: this must list your GPUs
docker run --rm -v /dev/null:/var/run/nvidia-container-devices/all ubuntu:22.04 nvidia-smi -L
```

`bin/devlab bootstrap --gpu` runs these checks first and stops with these setup steps if one fails.

### vGPU Guests (e.g. A10-24Q)

The same requirements and checks apply inside a VM with an NVIDIA vGPU. `nvidia-smi -L` shows the vGPU profile, e.g. `GPU 0: NVIDIA A10-24Q (UUID: GPU-...)`. Differences from a bare-metal GPU:

- **Guest driver**: install the NVIDIA vGPU guest driver from the NVIDIA Licensing Portal. It must match the vGPU software release of the hypervisor's vGPU manager. The public data center driver does not work in a vGPU guest. The NVIDIA Container Toolkit and `devlab` work the same on top of it.
- **Licensing**: an unlicensed vGPU runs at full capability for 20 minutes. After that NVIDIA degrades its performance, and degrades it further after 24 hours. The exact effect on CUDA depends on the vGPU release; see the [licensing guide](https://docs.nvidia.com/vgpu/latest/grid-licensing-user-guide/intro-to-grid-licensing.html). To license the VM ([NVIDIA docs](https://docs.nvidia.com/vgpu/latest/grid-licensing-user-guide/configuring-nls-licensed-client.html)):

  ```bash
  # Client configuration token from the NVIDIA Licensing Portal (or your DLS)
  sudo cp client_configuration_token_*.tok /etc/nvidia/ClientConfigToken/
  sudo chmod 744 /etc/nvidia/ClientConfigToken/client_configuration_token_*.tok
  # FeatureType=1 for a vGPU (license type follows the vGPU profile)
  sudo cp -n /etc/nvidia/gridd.conf.template /etc/nvidia/gridd.conf
  echo 'FeatureType=1' | sudo tee -a /etc/nvidia/gridd.conf
  sudo systemctl restart nvidia-gridd

  # Verify: License Status : Licensed (Expiry: ...)
  nvidia-smi -q | grep -i 'license status'
  ```

  `bin/devlab bootstrap --gpu` warns, but continues, when `nvidia-smi -q` reports the vGPU as unlicensed.
- **CUDA version**: container images must support the guest driver. CUDA 12 images run on any vGPU 16 (R535) or newer guest driver. CUDA 13 images need an R580+ driver. Check the driver's CUDA version in the `nvidia-smi` header.
- **No MIG on A10**: an A10 cannot be partitioned with MIG, so time slicing is the only way to share it between pods.
- **Unified memory**: CUDA unified (managed) memory is off by default on vGPUs. Your hypervisor admin must turn it on per vGPU, and NVIDIA documents it only for some profiles. Don't rely on managed memory (e.g. RMM managed memory) unless you have checked it is enabled.
- **Full-GPU profile**: A10-24Q uses the whole 24 GB A10, so no other VM shares the physical GPU. `nvidia-smi` in the guest reports slightly less than 24 GB total because of vGPU-reserved memory.

### What Bootstrap Does

1. Renders `cluster/nvkind-config-template.yaml` with `cluster/nvkind-values.yaml` (a Go template with [sprig](https://masterminds.github.io/sprig/) functions and `numGPUs`, as in nvkind). Then it creates the cluster with the built-in kind library.
2. Installs the NVIDIA Container Toolkit in each GPU worker and adds an `nvidia` containerd runtime (nvkind's node setup). It also applies the `nvidia` RuntimeClass.
3. Installs the `nvidia-device-plugin` Helm chart in the `nvidia` namespace with `config/gpu/nvidia-device-plugin-values.yaml`. This config turns on time slicing.
4. Waits until a node advertises allocatable `nvidia.com/gpu` (4 per physical GPU by default). Then it installs Linkerd as usual.

Masking `/proc/driver/nvidia/params` and removing unassigned `/dev/nvidia*` nodes can fail harmlessly on some toolkit versions. Bootstrap logs these as warnings and continues; the GPU capacity check catches a real failure.

### GPU Placement

By default the first worker gets every host GPU and the second worker is CPU-only. Edit `cluster/nvkind-values.yaml` to change this. Each `workers` entry is one worker node, and `devices` takes a GPU index, a list of indexes, or `all`:

```yaml
# One GPU per worker on a 2-GPU host
workers:
- devices: 0
- devices: 1
```

GPU workers get the `nvidia.com/gpu.present=true` label. The device plugin DaemonSet only runs on nodes with that label. Re-run `bin/devlab bootstrap --gpu` and recreate the cluster to apply changes.

### GPU Time Slicing

The device plugin [time-slices](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html) each physical GPU into 4 shares. A node with one GPU advertises `nvidia.com/gpu: 4`, so 4 pods that each request `nvidia.com/gpu: 1` run on the same GPU at once. The GPU switches between their CUDA contexts.

**Time slicing gives no memory or fault isolation.** Every pod sees the whole GPU and its full memory. Kubernetes cannot limit how much GPU memory a pod uses. One pod can use all the memory and make the others fail with out-of-memory errors. Each workload must limit its own GPU memory. For example, `config/dask/workers.yaml` gives each Dask worker a fixed 4.5 GiB RMM pool on a 24 GB GPU. A crash or GPU fault in one pod can also affect the others.

Other effects:

- A share is not a fixed fraction of compute. A pod alone on the GPU gets all of it, and 4 busy pods take turns.
- A pod that requests more than 1 `nvidia.com/gpu` is rejected with `UnexpectedAdmissionError`. Two shares of one GPU would not give it more GPU time (`failRequestsGreaterThanOne: true`).
- The resource name stays `nvidia.com/gpu`, so existing manifests work unchanged.

The config is in `config/gpu/nvidia-device-plugin-values.yaml`:

```bash
# Change the number of shares per GPU: edit `replicas` (must be >= 2), then
bin/devlab gpu-plugin

# Turn time slicing off for the whole cluster: set `config.default: exclusive`, then
bin/devlab gpu-plugin

# Turn it off on one node only (no reinstall; the plugin picks up the label change itself)
bin/devlab kubectl -- label node dev-lab-worker nvidia.com/device-plugin.config=exclusive --overwrite
# ...and back on
bin/devlab kubectl -- label node dev-lab-worker nvidia.com/device-plugin.config-
```

`bin/devlab gpu-plugin` re-runs the device plugin Helm install and waits for the new capacity. Pods already running on a share keep running, so delete them first if you reduce the share count.

For a worked example with 4 Dask workers sharing one A10, see [DASK-GPU-RUNBOOK.md](./DASK-GPU-RUNBOOK.md).

### Running GPU Workloads

GPU pods must request `nvidia.com/gpu` and set `runtimeClassName: nvidia`. The nvidia runtime is not the containerd default on the nodes:

```yaml
spec:
  runtimeClassName: nvidia
  containers:
    - name: app
      image: my-gpu-app:latest
      resources:
        limits:
          nvidia.com/gpu: 1
```

Smoke test:

```bash
bin/devlab kubectl -- apply -f config/gpu/gpu-test-pod.yaml
bin/devlab kubectl -- logs gpu-test     # GPU 0: NVIDIA ... (UUID: GPU-...)
bin/devlab kubectl -- delete pod gpu-test

# Allocatable GPU shares per node (GPUs column: 4 per physical GPU)
bin/devlab status
```

### GPU Troubleshooting

- **No node advertised nvidia.com/gpu capacity**: check the plugin logs with `bin/devlab kubectl -- logs -n nvidia -l app.kubernetes.io/name=nvidia-device-plugin -c nvidia-device-plugin-ctr`. Did you keep an existing cluster that was created without `--gpu`? Then delete it and re-bootstrap: `bin/devlab cleanup && bin/devlab bootstrap --gpu`.
- **Pod stuck in Pending**: all GPU shares are in use (4 per GPU by default). Check with `bin/devlab status`.
- **Pod fails with `UnexpectedAdmissionError`**: it requests more than 1 `nvidia.com/gpu` while time slicing is on.
- **`CUDA_ERROR_OUT_OF_MEMORY` with time slicing**: another pod on the same GPU used the memory. Limit each workload's GPU memory (see [GPU Time Slicing](#gpu-time-slicing)).
- **`requirement error: unsatisfied condition: cuda>=...`**: the image needs a newer driver than the host or vGPU guest has. Use an image built for an older CUDA version.
- **GPU slows down after ~20 minutes in a VM**: the vGPU is not licensed (see [vGPU Guests](#vgpu-guests-eg-a10-24q)).
- **`nvidia-smi: not found` in the pod**: the pod is missing `runtimeClassName: nvidia`.
- **GPU details per node**: `docker exec dev-lab-worker nvidia-smi -L` lists the GPUs a worker node sees.

## Image Workflow

For KinD clusters, there are two approaches for container images:

### Method 1: Direct Load (Recommended for Development)

```bash
# Build your image
docker build -t my-app:latest .

# Load directly into KinD cluster
bin/devlab load-image my-app:latest

# Deploy with imagePullPolicy: Never
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: my-app
        image: my-app:latest
        imagePullPolicy: Never
        ports:
        - containerPort: 80
EOF
```

### Method 2: Registry Push (For Simulation of Production)

```bash
# Build and tag for registry
docker build -t localhost:5000/my-app:latest .

# Push to local registry
docker push localhost:5000/my-app:latest

# Verify in registry
curl -s http://localhost:5000/v2/_catalog

# Note: Due to KinD networking, you'll need to load the image anyway:
bin/devlab load-image localhost:5000/my-app:latest
```

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
# Build your app image
docker build -t my-app:latest .

# Load into KinD
bin/devlab load-image my-app:latest

# Install chart with local image
helm install my-release ./my-chart \
  --set image.repository=my-app \
  --set image.tag=latest \
  --set image.pullPolicy=Never
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
curl -H 'x-canary: true' http://mesh-test.local:30080/

# Regular traffic goes to stable version
curl http://mesh-test.local:30080/
```

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
# Add Linkerd CLI to path
export PATH=$PATH:/home/jstevens/.linkerd2/bin

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
│     (nginx)     │────│   Controller    │
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

- ✅ **Health Probes**: Kubernetes liveness and readiness checks
- ✅ **Graceful Shutdown**: Proper SIGTERM handling
- ✅ **Resource Limits**: CPU and memory constraints
- ✅ **Security**: mTLS encryption for all service communication
- ✅ **Observability**: Comprehensive metrics and tracing
- ✅ **Zero Downtime**: Proven deployment strategies
- ✅ **Automated Testing**: Load generation and health verification

## Monitoring Access

### Port Forwards for Monitoring UIs

```bash
# Prometheus (metrics and targets)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# Access: http://localhost:9090

# Grafana (dashboards and visualization)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
# Access: http://localhost:3000
# Default: admin / prom-operator

# AlertManager (alert management)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093
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

## Cluster Autoscaling Simulation

### Deploy Sample Workload

```bash
# Deploy a resource-intensive workload
kubectl apply -f examples/sample-workload.yaml

# Monitor resource usage
kubectl top nodes
kubectl top pods

# Watch scaling in Grafana dashboards
```

### Manual Scaling Tests

```bash
# Scale deployment up
kubectl scale deployment sample-app --replicas=10

# Watch resource consumption
watch kubectl top nodes

# Check metrics in Prometheus
# Query: sum(rate(container_cpu_usage_seconds_total[5m])) by (pod)
```

## Directory Structure

```text
dev-lab/
├── cmd/devlab/                  # devlab CLI entry point (Go)
├── internal/
│   ├── cli/                     # Commands and flags
│   └── lab/                     # Bootstrap, deploy, GitOps, GPU, status and test logic
├── cluster/
│   ├── kind-config.yaml         # KinD cluster configuration
│   ├── nvkind-config-template.yaml # GPU cluster config template (bootstrap --gpu)
│   └── nvkind-values.yaml       # GPU placement per worker node
├── config/
│   ├── dask/                    # Dask scheduler + time-sliced GPU workers (DASK-GPU-RUNBOOK.md)
│   ├── gitops/                  # Flux GitRepository
│   ├── gpu/                     # NVIDIA RuntimeClass, device plugin values (time slicing), GPU smoke test pod
│   ├── monitoring/              # Prometheus stack Helm values
│   └── registry/                # Registry DaemonSet and UI
├── clusters/dev-lab/            # Flux Kustomizations for infrastructure/ and apps/
├── infrastructure/              # Deployed by Flux from Git (GitOps mode)
├── apps/
│   ├── mesh-test-app/           # Service mesh test app (Node.js, Redis, canary manifests and scripts)
│   └── mtls-test-app/           # mTLS verification app
├── scripts/
│   ├── build-distribution.sh    # Release tarballs (CI and local)
│   ├── fetch-tools.sh           # Pinned, checksum-verified kubectl/helm/linkerd/flux
│   ├── ci/build-version.sh      # CI build version
│   └── dist/                    # Files added to the tarballs
├── tests/dask/                  # Tests for the Dask sample workload
├── .github/workflows/build.yml  # CI: test, build, release
├── CHANGELOG.md                 # Release notes (one section per tag)
└── README.md                    # This file
```

Release tarballs contain only what runs the lab: `bin/`, `cluster/`, `config/`, `clusters/`, `apps/`, the guides and `licenses/` (see [From a Release Tarball](#from-a-release-tarball)).

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

- For KinD: Use `bin/devlab load-image <image>`
- Check image exists: `docker images | grep <image>`
- Verify imagePullPolicy is set to `Never` for local images

#### Monitoring Stack Not Starting

- Check resource constraints: `kubectl describe pods -n monitoring`
- Check the Helm release: `helm status kube-prometheus-stack -n monitoring`
- Check PVC status: `kubectl get pvc -n monitoring`

#### Registry Not Accessible

- Verify registry pod: `kubectl -n dev-lab-registry get pods`
- Check port mapping: `docker ps | grep dev-lab-control-plane`
- Test connectivity: `curl -v http://localhost:5000/v2/`

### Cleanup

```bash
# Delete the entire cluster
bin/devlab cleanup

# Optional: clean up unused images
docker system prune -f
```

## Advanced Configuration

### Custom Monitoring

Edit `config/monitoring/prometheus-values.yaml` to:

- Add custom metrics endpoints
- Configure alert rules
- Adjust resource limits
- Enable additional exporters

### Registry Configuration

Edit `config/registry/registry-daemonset.yaml` to:

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

## Performance Tips

1. **Resource Allocation**: The lightweight monitoring configuration reduces resource usage significantly
2. **Image Management**: Use `bin/devlab load-image` for development, registry for CI/CD simulation
3. **Persistent Storage**: Registry data persists in `/var/lib/registry` on control-plane node
4. **Port Forwarding**: Use kubectl port-forward instead of NodePort for better performance

## License

This development lab setup is provided as-is for educational and development purposes.
