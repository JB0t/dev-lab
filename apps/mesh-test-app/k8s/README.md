# Linkerd + Flagger Canary Deployment Configuration

<!-- docgen:begin id=apps/mesh-test-app/k8s:overview scope=apps/mesh-test-app/k8s hash=543cb83b5787 -->
This module defines Kubernetes manifests and scripts for a mesh test application. It includes base deployment, redis service, canary configuration, and load testing setup. The module uses Linkerd for service mesh features and Flagger for progressive delivery.

The module combines standard Kubernetes resources with service mesh specific configurations. It sets up a test application with primary and canary deployments. The canary uses Flagger for automated rollouts with metrics and webhooks. Linkerd metrics templates define success rate and latency checks for canary analysis.

The module includes monitoring and testing scripts. The `test-load-balancing.sh` script generates load and checks distribution across pods. The `monitor-load-balancing.sh` script provides real-time load distribution metrics. The kustomization file ties all components together into a single deployment. The manifests define namespaces, deployments, services, ingresses, pod disruption budgets, and custom resources for Flagger and Linkerd integration.
<!-- docgen:end id=apps/mesh-test-app/k8s:overview -->

This directory contains the minimal, essential configuration for a working Linkerd service mesh canary deployment using Flagger and Prometheus metrics.

## ✅ Essential Files

### Core Application

- **`base.yaml`** - Application deployment, service, and ingress
- **`redis.yaml`** - Redis backend dependency

### Progressive Delivery (Flagger)

- **`canary.yaml`** - Flagger canary configuration with success rate thresholds
- **`loadtester.yaml`** - Flagger load tester for pre-rollout webhooks

### Linkerd + Prometheus Integration

- **`linkerd-metric-templates.yaml`** - Prometheus queries for success rate metrics
- **`linkerd-podmonitor-debug.yaml`** - Official Linkerd proxy metrics collection

### Deployment

- **`kustomization.yaml`** - Kustomize configuration for GitOps deployment

## 🔧 Key Configuration Details

### Flagger Bypass for Prometheus

The Flagger deployment requires this annotation to bypass Linkerd proxy for Prometheus communication:

```yaml
config.linkerd.io/skip-outbound-ports: "9090"
```

Applied with:

```bash
kubectl patch deployment flagger -n linkerd -p '{"spec":{"template":{"metadata":{"annotations":{"config.linkerd.io/skip-outbound-ports":"9090"}}}}}'
```

### Prometheus Service Discovery

All monitoring resources require this label for Prometheus operator discovery:

```yaml
metadata:
  labels:
    release: kube-prometheus-stack
```

## 🚀 Deployment

Deploy with Kustomize:

```bash
kubectl apply -k .
```

Or deploy individual files:

```bash
kubectl apply -f base.yaml -f redis.yaml -f canary.yaml -f loadtester.yaml -f linkerd-metric-templates.yaml -f linkerd-podmonitor-debug.yaml
```

## 📊 Canary Progression

The canary will automatically progress through these weights based on success rate metrics:

- 10% → 20% → 30% → 40% → 50% → Promoted

Success rate threshold: **95%**  
Evaluation interval: **30 seconds**  
Max weight: **50%**

## 🔍 Monitoring

Check canary status:

```bash
kubectl get canary mesh-test-app -n mesh-test
```

View Flagger logs:

```bash
kubectl logs -n linkerd deployment/flagger
```

## 🎯 Prerequisites

1. **Linkerd** service mesh installed and running
2. **Flagger** deployed in linkerd namespace with proxy bypass configured
3. **Prometheus** operator with kube-prometheus-stack
4. **Linkerd namespace** has injection enabled: `linkerd.io/inject: enabled`

<!-- docgen:begin id=apps/mesh-test-app/k8s:reference scope=apps/mesh-test-app/k8s hash=543cb83b5787 -->
## Reference

### `base.yaml`

- **`Namespace/mesh-test`** (manifest)
- **`Deployment/mesh-test-app`** (manifest)
- **`Service/mesh-test-app-service`** (manifest)
- **`Ingress/mesh-test-app-ingress`** (manifest)

### `canary.yaml`

- **`Canary/mesh-test-app`** (manifest)

### `kustomization.yaml`

- **`Kustomization/mesh-test-app`** (manifest)

### `linkerd-metric-templates.yaml`

- **`MetricTemplate/linkerd-success-rate`** (manifest)
- **`MetricTemplate/linkerd-request-duration`** (manifest)
- **`MetricTemplate/linkerd-traffic-success-rate`** (manifest)

### `linkerd-podmonitor-debug.yaml`

- **`PodMonitor/linkerd-proxy-proper`** (manifest)

### `loadtester.yaml`

- **`Deployment/flagger-loadtester`** (manifest)
- **`Service/flagger-loadtester`** (manifest)

### `pod-disruption-budget.yaml`

- **`PodDisruptionBudget/mesh-test-app-pdb`** (manifest)
- **`PodDisruptionBudget/mesh-test-app-canary-pdb`** (manifest)

### `redis.yaml`

- **`ConfigMap/redis-config`** (manifest)
- **`Deployment/redis`** (manifest)
- **`Service/redis-service`** (manifest)
<!-- docgen:end id=apps/mesh-test-app/k8s:reference -->
