# Linkerd + Flagger Canary Deployment Configuration

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
