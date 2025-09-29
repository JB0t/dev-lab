# Local Kubernetes Development Lab

A comprehensive local development environment with **dual deployment options**: traditional script-based or modern GitOps-based, now featuring a **platform-agnostic Python CLI**.

> **📖 For detailed setup instructions, see [DEPLOYMENT-GUIDE.md](./DEPLOYMENT-GUIDE.md)**
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

## Quick Start

### Option 1: Python CLI (Recommended)

```bash
# Setup Python environment
python3 python/setup.py

# Build local tool container images (optional, built automatically when needed)
./devlab build-tools

# Bootstrap the cluster
./devlab bootstrap

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
<!-- TODO: update canary tests (include flagger) -->

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
│   └── kind-config.yaml         # KinD cluster configuration
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
