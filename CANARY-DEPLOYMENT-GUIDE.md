# GitOps Canary Deployment Guide

This guide demonstrates a complete GitOps canary deployment workflow using Flagger, Linkerd, and the local container registry.

## Overview

The mesh-test-app demonstrates zero-downtime deployments with:

- **Flagger**: Progressive delivery controller
- **Linkerd**: Service mesh for traffic management and metrics
- **Local Registry**: `localhost:5000` for container images
- **GitOps**: Flux CD manages deployments from Git

## Prerequisites

1. **Environment Setup**:

   ```bash
   # Bootstrap the dev-lab environment
   ./devlab bootstrap
   
   # Deploy GitOps infrastructure
   ./devlab deploy-gitops
   ```

1. **Verify Flagger and Registry**:

   ```bash
   # Check Flagger is running
   kubectl get pods -n flagger-system
   
   # Verify local registry is accessible
   curl -s http://localhost:5000/v2/_catalog
   ```

## Step 1: Build and Push v2 Image

### 1.1 Modify the Application (Create v2)

Let's make a visible change to demonstrate the canary deployment:

```bash
cd /home/jstevens/git/jbotstevens/dev-lab/apps/mesh-test-app
```

Update the main page to show version v2:

```javascript
// In server.js, update the HTML response to show v2
// This change will be visible during canary testing
```

### 1.2 Build the v2 Image

```bash
# Build the v2 image
docker build -t localhost:5000/mesh-test-app:v2 .

# Push to local registry
docker push localhost:5000/mesh-test-app:v2

# Verify the image was pushed
curl -s http://localhost:5000/v2/mesh-test-app/tags/list
```

Expected output:

```json
{"name":"mesh-test-app","tags":["v1","v2"]}
```

## Step 2: Trigger Canary Deployment via GitOps

### 2.1 Update the Deployment Manifest

Edit the deployment to use the new v2 image:

```bash
cd /home/jstevens/git/jbotstevens/dev-lab
```

Update `apps/mesh-test-app/k8s/base.yaml`:

```yaml
containers:
- name: mesh-test-app
  image: localhost:5000/mesh-test-app:v2  # ← Changed from v1 to v2
  env:
  - name: APP_VERSION
    value: "v2"  # ← Update version env var
```

### 2.2 Commit and Push Changes

```bash
# Add the changes
git add apps/mesh-test-app/k8s/base.yaml

# Commit with descriptive message
git commit -m "feat: trigger canary deployment - update mesh-test-app to v2

- Updated image tag from v1 to v2
- Updated APP_VERSION environment variable
- This will trigger Flagger canary deployment process"

# Push to trigger GitOps
git push origin main
```

### 2.3 Force Flux Reconciliation (Optional)

To trigger immediately without waiting for Flux's sync interval:

```bash
# Force Git source sync
flux reconcile source git dev-lab-repo

# Force kustomization sync
flux reconcile ks dev-lab-apps
```

## Step 3: Monitor the Canary Deployment

### 3.1 Watch Canary Progress

```bash
# Monitor canary status
kubectl get canary mesh-test-app -n mesh-test -w

# Detailed canary information
kubectl describe canary mesh-test-app -n mesh-test
```

### 3.2 Monitor Pods and Services

```bash
# Watch pods during deployment
kubectl get pods -n mesh-test -w

# Check services (primary and canary)
kubectl get svc -n mesh-test
```

### 3.3 View Flagger Logs

```bash
# Monitor Flagger decision making
kubectl logs -n flagger-system deployment/flagger -f
```

## Step 4: Canary Deployment Process

### 4.1 Expected Timeline

| Phase | Duration | Traffic Split | Actions |
|-------|----------|---------------|---------|
| **Initialize** | 30s | 0% → 10% | Canary pods created, health checks |
| **Step 1** | 30s | 10% | Load tests, metrics validation |
| **Step 2** | 30s | 20% | Continued monitoring |
| **Step 3** | 30s | 30% | Stress testing |
| **Step 4** | 30s | 40% | Final validation |
| **Step 5** | 30s | 50% | Last checks before promotion |
| **Promote** | 60s | 100% | Replace primary, cleanup canary |

**Total Duration**: ~15-20 minutes

### 4.2 Health Checks Performed

1. **Pre-rollout Checks**:
   - UI health endpoint validation
   - Redis connectivity test
   - Basic functionality verification

1. **Load Tests** (per traffic step):
   - UI functionality testing (`hey` load generator)
   - Health endpoint stress testing
   - Concurrent request handling

1. **Metrics Validation**:
   - **Success Rate**: ≥95% (from Linkerd metrics)
   - **Latency**: ≤500ms (P99 response time)

1. **End-to-End Tests**:
   - Redis data persistence
   - Counter increment functionality
   - Multi-endpoint validation

## Step 5: Monitor with Linkerd Viz

### 5.1 Access Linkerd Dashboard

```bash
# Start the dashboard (if not already running)
kubectl port-forward -n linkerd-viz svc/web 50750:8084 --address=0.0.0.0

# Or use the devlab wrapper (if available)
./devlab kubectl -- port-forward -n linkerd-viz svc/web 50750:8084 --address=0.0.0.0
```

Visit: `<http://localhost:50750>`

### 5.2 Key Metrics to Watch

- **Success Rate**: Real-time traffic success percentage
- **Request Volume**: Traffic distribution between primary/canary
- **Latency**: P50, P95, P99 response times
- **Traffic Split**: Visual representation of canary progression

## Step 6: Possible Outcomes

### 6.1 Successful Promotion ✅

```bash
# Successful canary will show:
kubectl get canary mesh-test-app -n mesh-test
# STATUS: Succeeded
# CANARY WEIGHT: 0 (promoted to primary)
```

**What happens**:

1. All health checks pass
2. Metrics stay within thresholds
3. Canary becomes the new primary
4. Old primary pods are terminated
5. Traffic routes 100% to v2

### 6.2 Automatic Rollback ❌

```bash
# Failed canary will show:
kubectl get canary mesh-test-app -n mesh-test
# STATUS: Failed
# CANARY WEIGHT: 0 (rolled back)
```

**Common failure reasons**:

- Success rate drops below 95%
- Latency exceeds 500ms
- Load test failures
- Health check failures
- Redis connectivity issues

## Step 7: Validation and Testing

### 7.1 Test the Application During Canary

```bash
# Get the service endpoint
kubectl get svc mesh-test-app -n mesh-test

# Test the application (this will hit both v1 and v2 during canary)
curl http://mesh-test-app.mesh-test.svc.cluster.local/

# Or use port-forward for external access
kubectl port-forward svc/mesh-test-app 8080:80 -n mesh-test
curl http://localhost:8080/
```

### 7.2 Verify Version Distribution

During the canary, you should see both versions responding:

- ~90% requests show "v1" (primary)  
- ~10% requests show "v2" (canary)

### 7.3 Check Redis Functionality

```bash
# Test counter functionality (stored in Redis)
for i in {1..10}; do
  curl http://localhost:8080/
  sleep 1
done

# Verify counter increments correctly across versions
```

## Step 8: Cleanup and Reset

### 8.1 Monitor Cleanup

After successful promotion:

```bash
# Check that old pods are terminated
kubectl get pods -n mesh-test

# Verify only v2 pods remain
kubectl describe deployment mesh-test-app -n mesh-test | grep Image
```

### 8.2 Reset for Next Deployment

To test another canary deployment:

```bash
# Build v3 image
docker build -t localhost:5000/mesh-test-app:v3 .
docker push localhost:5000/mesh-test-app:v3

# Update deployment to v3 and commit
# Repeat the GitOps process
```

## Troubleshooting

### Common Issues

1. **Image Pull Errors**:

   ```bash
   # Verify local registry connectivity
   docker pull localhost:5000/mesh-test-app:v2
   ```

1. **Flagger Not Detecting Changes**:

   ```bash
   # Force Flux sync
   flux reconcile ks dev-lab-apps
   
   # Check Flagger logs
   kubectl logs -n flagger-system deployment/flagger
   ```

1. **Load Test Failures**:

   ```bash
   # Check loadtester pod
   kubectl get pods -n mesh-test | grep loadtester
   kubectl logs -n mesh-test deployment/flagger-loadtester
   ```

1. **Metrics Issues**:

   ```bash
   # Verify Prometheus connectivity
   kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
   # Visit http://localhost:9090 and test metric queries
   ```

### Useful Commands

```bash
# Quick status check
kubectl get canary,pods,svc -n mesh-test

# Detailed events
kubectl get events -n mesh-test --sort-by='.lastTimestamp'

# Flagger status
kubectl get canary -A

# Force canary restart (if stuck)
kubectl annotate canary mesh-test-app -n mesh-test flagger.app/restart=$(date +%s)
```

## Architecture Summary

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│     Git     │───▶│     Flux     │───▶│ Kubernetes  │
│ Repository  │    │   GitOps     │    │   Cluster   │
└─────────────┘    └──────────────┘    └─────────────┘
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
                   │   Flagger   │    │   Linkerd   │    │   Registry  │
                   │ Progressive │    │ Service Mesh│    │ localhost:  │
                   │  Delivery   │    │  & Metrics  │    │    5000     │
                   └─────────────┘    └─────────────┘    └─────────────┘
```

This GitOps canary deployment process provides:

- ✅ **Zero-downtime deployments**
- ✅ **Automated rollback on failures**  
- ✅ **Comprehensive testing at each step**
- ✅ **Real-time traffic and metrics monitoring**
- ✅ **Full GitOps workflow integration**

The entire process is declarative, version-controlled, and automatically handles the complexity of progressive traffic shifting and validation! 🚀
