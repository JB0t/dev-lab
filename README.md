# Local Kubernetes Development Lab

A comprehensive local development environment with **dual deployment options**: traditional script-based or modern GitOps-based, now featuring a **platform-agnostic Python CLI**.

> **📖 For GitOps setup guide, see [GITOPS-GUIDE.md](./GITOPS-GUIDE.md)**

## Features

- **Platform Agnostic**: Python CLI with Docker-only dependency (works on Windows, macOS, Linux)
- **High Availability Kubernetes Cluster**: 3-node KinD cluster (1 control-plane + 2 workers)
- **GitOps with Flux CD**: Complete Flux v2 setup with source/kustomize/helm/notification controllers
- **Service Mesh Testing**: Complete Linkerd service mesh with canary deployments and mTLS
- **Monitoring Stack**: Lightweight Prometheus, Grafana, and AlertManager
- **Local Container Registry**: Docker registry accessible at localhost:5000
- **Ingress Controller**: NGINX ingress for local service exposure
- **Metrics Server**: For cluster autoscaling and resource monitoring
- **Container-based Tools**: All Kubernetes tools run in containers (no local installation needed)
- **GPU-Enabled Option**: `./devlab bootstrap --gpu` builds the same cluster with [nvkind](https://github.com/NVIDIA/nvkind) and NVIDIA GPUs on the workers

## Quick Start

### Option 1: Python CLI (Recommended)

```bash
# Setup Python environment
python3 python/setup.py

# Build local tool container images (optional, built automatically when needed)
./devlab build-tools

# Bootstrap the cluster
./devlab bootstrap

# OR bootstrap a GPU-enabled cluster (Linux + NVIDIA GPU, see below)
./devlab bootstrap --gpu

# Deploy using traditional method
./devlab deploy-traditional

# OR deploy using GitOps method
./devlab deploy-gitops

# Check status
./devlab status

# Use container-based tools
./devlab kubectl -- get pods -A
./devlab helm -- list -A
./devlab linkerd -- check
./devlab flux -- get all -A

# Cleanup when done
./devlab cleanup
```

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

## GPU-Enabled Cluster (nvkind)

`./devlab bootstrap --gpu` creates the same `dev-lab` cluster (same name, ports, registry and labels) with [nvkind](https://github.com/NVIDIA/nvkind) instead of plain KinD, then installs the [NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin) so pods can request `nvidia.com/gpu`. Each physical GPU is [time-sliced](#gpu-time-slicing) into 4 shares by default. Everything after bootstrap (`deploy-traditional`, `deploy-gitops`, `status`, `cleanup`) works the same.

### Host Requirements

nvkind needs the host GPU driver, and it runs `kind` and `kubectl` itself. So unlike the default bootstrap, `--gpu` needs these on the host:

- Linux (or WSL2) with an NVIDIA GPU and driver: `nvidia-smi -L` lists your GPUs
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- `kind` and `kubectl` on `PATH`
- `nvkind` on `PATH`:

  ```bash
  go install github.com/NVIDIA/nvkind/cmd/nvkind@latest
  # or, without a local Go toolchain:
  docker run --rm -v $PWD/bin/:/go/bin/ golang:1.23 go install github.com/NVIDIA/nvkind/cmd/nvkind@latest
  ```

Configure Docker so nvkind can inject GPUs into the KinD node containers (one-time):

```bash
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default --cdi.enabled
sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place
sudo systemctl restart docker

# Verify: this must list your GPUs
docker run --rm -v /dev/null:/var/run/nvidia-container-devices/all ubuntu:22.04 nvidia-smi -L
```

`./devlab bootstrap --gpu` runs these checks first and stops with these setup steps if one fails.

### vGPU Guests (e.g. A10-24Q)

The same requirements and checks apply inside a VM with an NVIDIA vGPU. `nvidia-smi -L` shows the vGPU profile, e.g. `GPU 0: NVIDIA A10-24Q (UUID: GPU-...)`. Differences from a bare-metal GPU:

- **Guest driver**: install the NVIDIA vGPU guest driver from the NVIDIA Licensing Portal. It must match the vGPU software release of the hypervisor's vGPU manager. The public data center driver does not work in a vGPU guest. The NVIDIA Container Toolkit and nvkind work the same on top of it.
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

  `./devlab bootstrap --gpu` warns, but continues, when `nvidia-smi -q` reports the vGPU as unlicensed.
- **CUDA version**: container images must support the guest driver. CUDA 12 images run on any vGPU 16 (R535) or newer guest driver. CUDA 13 images need an R580+ driver. Check the driver's CUDA version in the `nvidia-smi` header.
- **No MIG on A10**: an A10 cannot be partitioned with MIG, so time slicing is the only way to share it between pods.
- **Unified memory**: CUDA unified (managed) memory is off by default on vGPUs. Your hypervisor admin must turn it on per vGPU, and NVIDIA documents it only for some profiles. Don't rely on managed memory (e.g. RMM managed memory) unless you have checked it is enabled.
- **Full-GPU profile**: A10-24Q uses the whole 24 GB A10, so no other VM shares the physical GPU. `nvidia-smi` in the guest reports slightly less than 24 GB total because of vGPU-reserved memory.

### What Bootstrap Does

1. Renders `cluster/nvkind-config-template.yaml` with `cluster/nvkind-values.yaml`. Then it creates the cluster with `nvkind cluster create`.
2. nvkind installs the NVIDIA Container Toolkit in each GPU worker and adds an `nvidia` containerd runtime. It also registers the `nvidia` RuntimeClass.
3. Installs the `nvidia-device-plugin` Helm chart in the `nvidia` namespace with `config/gpu/nvidia-device-plugin-values.yaml`. This config turns on time slicing.
4. Waits until a node advertises allocatable `nvidia.com/gpu` (4 per physical GPU by default). Then it installs Linkerd as usual.

`nvkind cluster create` can exit with an error from harmless unmount failures after the cluster is up. Bootstrap continues when the cluster exists. The GPU capacity check catches a real failure.

### GPU Placement

By default the first worker gets every host GPU and the second worker is CPU-only. Edit `cluster/nvkind-values.yaml` to change this. Each `workers` entry is one worker node, and `devices` takes a GPU index, a list of indexes, or `all`:

```yaml
# One GPU per worker on a 2-GPU host
workers:
- devices: 0
- devices: 1
```

GPU workers get the `nvidia.com/gpu.present=true` label. The device plugin DaemonSet only runs on nodes with that label. Re-run `./devlab bootstrap --gpu` and recreate the cluster to apply changes.

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
./devlab gpu-plugin

# Turn time slicing off for the whole cluster: set `config.default: exclusive`, then
./devlab gpu-plugin

# Turn it off on one node only (no reinstall; the plugin picks up the label change itself)
./devlab kubectl -- label node dev-lab-worker nvidia.com/device-plugin.config=exclusive --overwrite
# ...and back on
./devlab kubectl -- label node dev-lab-worker nvidia.com/device-plugin.config-
```

`./devlab gpu-plugin` re-runs the device plugin Helm install and waits for the new capacity. Pods already running on a share keep running, so delete them first if you reduce the share count.

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
./devlab kubectl -- apply -f config/gpu/gpu-test-pod.yaml
./devlab kubectl -- logs gpu-test     # GPU 0: NVIDIA ... (UUID: GPU-...)
./devlab kubectl -- delete pod gpu-test

# Allocatable GPU shares per node (GPUs column: 4 per physical GPU)
./devlab status
```

### GPU Troubleshooting

- **No node advertised nvidia.com/gpu capacity**: check the plugin logs with `./devlab kubectl -- logs -n nvidia -l app.kubernetes.io/name=nvidia-device-plugin -c nvidia-device-plugin-ctr`. Did you keep an existing cluster that was created without `--gpu`? Then delete it and re-bootstrap: `./devlab cleanup && ./devlab bootstrap --gpu`.
- **Pod stuck in Pending**: all GPU shares are in use (4 per GPU by default). Check with `./devlab status`.
- **Pod fails with `UnexpectedAdmissionError`**: it requests more than 1 `nvidia.com/gpu` while time slicing is on.
- **`CUDA_ERROR_OUT_OF_MEMORY` with time slicing**: another pod on the same GPU used the memory. Limit each workload's GPU memory (see [GPU Time Slicing](#gpu-time-slicing)).
- **`requirement error: unsatisfied condition: cuda>=...`**: the image needs a newer driver than the host or vGPU guest has. Use an image built for an older CUDA version.
- **GPU slows down after ~20 minutes in a VM**: the vGPU is not licensed (see [vGPU Guests](#vgpu-guests-eg-a10-24q)).
- **`nvidia-smi: not found` in the pod**: the pod is missing `runtimeClassName: nvidia`.
- **GPU details per node**: run `kind export kubeconfig --name dev-lab`, then `nvkind cluster print-gpus --name dev-lab`. nvkind reads the cluster through your host kubeconfig. The `./devlab` kubeconfig in `.kube/config` uses an address that only resolves inside the `kind` Docker network.

## Image Workflow

For KinD clusters, there are two approaches for container images:

### Method 1: Direct Load (Recommended for Development)

```bash
# Build your image
docker build -t my-app:latest .

# Load directly into KinD cluster
kind load docker-image my-app:latest --name dev-lab

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
kind load docker-image localhost:5000/my-app:latest --name dev-lab
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
kind load docker-image my-app:latest --name dev-lab

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
│   ├── kind-config.yaml         # KinD cluster configuration
│   ├── nvkind-config-template.yaml # GPU cluster config template (bootstrap --gpu)
│   └── nvkind-values.yaml       # GPU placement per worker node
├── config/
│   ├── dask/                    # Dask scheduler + time-sliced GPU workers (DASK-GPU-RUNBOOK.md)
│   └── gpu/                     # NVIDIA RuntimeClass, device plugin values (time slicing), GPU smoke test pod
├── monitoring/
│   ├── prometheus-values-lightweight.yaml    # Prometheus stack values
│   └── custom-monitoring.yaml  # Additional monitoring resources
├── registry/
│   └── registry-k8s-daemonset.yaml          # Registry deployment
├── scripts/
│   ├── setup.sh                # Main setup script
│   └── test-environment.sh     # Environment testing script
├── examples/
│   └── sample-workload.yaml    # Example workload for testing
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

- For KinD: Use `kind load docker-image <image> --name dev-lab`
- Check image exists: `docker images | grep <image>`
- Verify imagePullPolicy is set to `Never` for local images

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
./scripts/setup.sh cleanup

# Or manually:
kind delete cluster --name dev-lab
docker system prune -f  # Optional: clean up images
```

## Advanced Configuration

### Custom Monitoring

Edit `monitoring/prometheus-values-lightweight.yaml` to:

- Add custom metrics endpoints
- Configure alert rules
- Adjust resource limits
- Enable additional exporters

### Registry Configuration

Edit `registry/registry-k8s-daemonset.yaml` to:

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
2. **Image Management**: Use `kind load` for development, registry for CI/CD simulation
3. **Persistent Storage**: Registry data persists in `/var/lib/registry` on control-plane node
4. **Port Forwarding**: Use kubectl port-forward instead of NodePort for better performance

## License

This development lab setup is provided as-is for educational and development purposes.
