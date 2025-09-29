# Service Mesh and Zero-Downtime Deployment Testing

This application provides a comprehensive testing environment for service mesh functionality and zero-downtime deployment strategies using Linkerd and Kubernetes.

## Features

### Application Stack

- **Node.js Web Application**: Simple API with health checks, metrics, and database interaction
- **Redis Database**: Backend storage with service mesh mTLS protection
- **Prometheus Metrics**: Application and custom metrics for monitoring
- **Health Endpoints**: Liveness and readiness probes for deployment verification

### Service Mesh Testing

- **Linkerd Integration**: Automatic proxy injection and mTLS encryption
- **Traffic Splitting**: Canary deployments with configurable traffic weights
- **Observability**: Real-time metrics, tracing, and traffic analysis
- **Security**: mTLS encryption between all services

### Zero-Downtime Deployment

- **Canary Strategy**: Gradual traffic shifting from stable to new version
- **Health Monitoring**: Continuous health checks during deployments
- **Load Testing**: Automated load generation to verify zero downtime
- **Rollback Capability**: Quick rollback to stable version if issues detected

## Quick Start

### 1. Setup Service Mesh Environment

```bash
# Install Linkerd and deploy the application
./scripts/setup-service-mesh.sh
```

This will:

- Install Linkerd CLI and control plane
- Deploy Linkerd Viz for observability
- Build and deploy the test application
- Configure automatic proxy injection

### 2. Test Basic Functionality

```bash
# Port-forward to the application
kubectl port-forward -n mesh-test svc/mesh-test-app-service 8080:80

# Test endpoints
curl http://localhost:8080/health
curl http://localhost:8080/api/data
curl http://localhost:8080/metrics
```

### 3. Run Zero-Downtime Deployment Test

```bash
# Run comprehensive test suite
./scripts/test-suite.sh

# Or with custom parameters (duration, RPS, workers)
./scripts/test-suite.sh 120 20 10
```

### 4. Manual Canary Deployment

```bash
# Deploy canary version (10% traffic)
./scripts/canary-deploy.sh deploy

# Monitor traffic distribution
./scripts/canary-deploy.sh test 50

# Adjust traffic weights
./scripts/canary-deploy.sh weights 70 30

# Promote to stable or rollback
./scripts/canary-deploy.sh promote
./scripts/canary-deploy.sh rollback
```

## Application Endpoints

### Health Checks

- `GET /health` - General health status
- `GET /health/live` - Liveness probe (should always return 200)
- `GET /health/ready` - Readiness probe (checks database connectivity)

### API Endpoints

- `GET /` - Main application endpoint with version info
- `GET /api/data` - Sample data from database
- `POST /api/load/:duration` - Simulate load for testing

### Monitoring

- `GET /metrics` - Prometheus metrics endpoint

### Administration

- `POST /admin/shutdown` - Graceful shutdown (for testing)

## Service Mesh Features

### mTLS Verification

```bash
# Check mTLS status
linkerd viz edges -n mesh-test

# Monitor encrypted traffic
linkerd viz tap -n mesh-test --to svc/redis-service
```

### Traffic Analysis

```bash
# Service statistics
linkerd viz stat -n mesh-test

# Real-time traffic
linkerd viz top -n mesh-test

# Traffic splitting status
kubectl get trafficsplit -n mesh-test
```

### Observability Dashboard

```bash
# Open Linkerd dashboard
kubectl port-forward -n linkerd-viz svc/web 8084:8084
# Visit http://localhost:8084
```

## Deployment Strategies

### Canary Deployment Process

1. **Deploy Canary**: Start with 10% traffic to new version
2. **Monitor Metrics**: Check error rates, latency, and health
3. **Gradual Increase**: Incrementally increase traffic (20%, 50%, 80%)
4. **Promote or Rollback**: Based on monitoring results

### Traffic Splitting Examples

```bash
# 90% stable, 10% canary
./scripts/canary-deploy.sh weights 90 10

# 50/50 split for A/B testing
./scripts/canary-deploy.sh weights 50 50

# Blue/green deployment (100% switch)
./scripts/canary-deploy.sh weights 0 100
```

## Testing Scenarios

### 1. Basic Zero-Downtime Test

```bash
# Test with moderate load
./scripts/test-suite.sh 60 10 5
```

### 2. High-Load Stress Test

```bash
# Test with heavy load
./scripts/test-suite.sh 300 50 20
```

### 3. Extended Reliability Test

```bash
# Long-running test
./scripts/test-suite.sh 1800 15 10  # 30 minutes
```

## Monitoring and Verification

### Key Metrics to Monitor

1. **Request Success Rate**: Should remain 100% during deployments
2. **Response Latency**: Should not increase significantly
3. **Health Check Status**: Should never fail during deployment
4. **Service Mesh mTLS**: All traffic should be encrypted

### Expected Results

✅ **Successful Zero-Downtime Deployment**:

- 0 request failures during deployment
- 0 health check failures
- Smooth traffic transition between versions
- mTLS encryption maintained

❌ **Failed Deployment** (triggers rollback):

- Increased error rate in canary version
- Health check failures
- Significant latency increase

## Troubleshooting

### Common Issues

**Pods in ImagePullBackOff**:

```bash
# Rebuild and load images
docker build -t mesh-test-app:v1 .
kind load docker-image mesh-test-app:v1 --name dev-lab
```

**Linkerd Proxy Injection Not Working**:

```bash
# Check namespace annotation
kubectl get namespace mesh-test -o yaml | grep linkerd.io/inject

# Manual injection
kubectl get deployment mesh-test-app -n mesh-test -o yaml | linkerd inject - | kubectl apply -f -
```

**Service Not Responding**:

```bash
# Check pod status
kubectl get pods -n mesh-test

# Check logs
kubectl logs -n mesh-test -l app=mesh-test-app

# Check service endpoints
kubectl get endpoints -n mesh-test
```

### Debugging Commands

```bash
# Application logs
kubectl logs -n mesh-test -l app=mesh-test-app -f

# Linkerd proxy logs
kubectl logs -n mesh-test <pod-name> -c linkerd-proxy

# Service mesh configuration
linkerd viz check

# Traffic analysis
linkerd viz tap -n mesh-test

# Performance metrics
kubectl top pods -n mesh-test
```

## Architecture

```
┌─────────────────┐    ┌─────────────────┐
│   Load Balancer │    │     Ingress     │
│     (nginx)     │────│   Controller    │
└─────────────────┘    └─────────────────┘
                                │
                       ┌─────────────────┐
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

### Components

- **Application Pods**: Node.js app with Linkerd proxy sidecars
- **Redis**: Database with mTLS encryption via service mesh
- **TrafficSplit**: Linkerd resource for canary deployments
- **ServiceMonitor**: Prometheus metrics collection
- **Ingress**: External access to the application

## Advanced Configuration

### Custom Traffic Splitting Rules

Edit `k8s/canary.yaml` to modify traffic splitting behavior:

```yaml
apiVersion: split.smi-spec.io/v1alpha1
kind: TrafficSplit
metadata:
  name: mesh-test-app-split
spec:
  service: mesh-test-app-service
  backends:
  - service: mesh-test-app-service-v1
    weight: 80  # Adjust weights
  - service: mesh-test-app-service-v2
    weight: 20
```

### Application Configuration

Environment variables in deployment:

- `APP_VERSION`: Version identifier for tracking
- `REDIS_URL`: Database connection string
- `PORT`: Application port (default: 3000)

### Resource Limits

Adjust in deployment manifests:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi
```

## Performance Benchmarks

Typical performance on KinD cluster:

- **Baseline**: ~100-200ms response time at 10 RPS
- **During Deployment**: <5% latency increase
- **Zero Downtime**: 100% success rate maintained
- **mTLS Overhead**: <10ms additional latency

## Best Practices

1. **Health Checks**: Always implement proper liveness and readiness probes
2. **Graceful Shutdown**: Handle SIGTERM signals properly
3. **Resource Limits**: Set appropriate CPU and memory limits
4. **Gradual Rollout**: Start with small traffic percentages (5-10%)
5. **Monitoring**: Watch metrics continuously during deployments
6. **Rollback Strategy**: Have automated rollback triggers

## License

This testing framework is provided for educational and development purposes.
