# Linkerd + Flagger Canary Deployment Configuration

<!-- docgen:begin id=apps/mesh-test-app/k8s:overview scope=apps/mesh-test-app/k8s hash=2d2b6b4f4e7d -->
This module defines the Kubernetes manifests and configurations for the `mesh-test-app`, a service mesh testing application designed for progressive delivery and load balancing validation. It includes core application components such as a `Deployment`, `Service`, and `Ingress`, along with supporting infrastructure like a Redis instance for testing and a `PodDisruptionBudget` to ensure availability during updates. The module also integrates with Linkerd for service mesh observability and Flagger for canary deployments.

The module leverages Kustomize to compose and manage multiple Kubernetes resources, including Flagger's `Canary` custom resource for progressive delivery, `MetricTemplate` definitions for Linkerd-based metrics, and `PodMonitor` configurations for detailed proxy metrics. It also includes a `loadtester` deployment that provides webhooks for functional and load testing during canary releases.

Scripts such as `test-load-balancing.sh` and `monitor-load-balancing.sh` are included to facilitate real-time monitoring and demonstration of load distribution across pods, providing visibility into how traffic is balanced within the service mesh. These scripts interact with Prometheus endpoints to gather metrics on request rates, pod distribution, and load balancing evenness, supporting both automated canary analysis and manual validation of service mesh behavior.
<!-- docgen:end id=apps/mesh-test-app/k8s:overview -->

This directory contains the minimal, essential configuration for a working Linkerd service mesh canary deployment using Flagger and Prometheus metrics.

## Essential Files

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

## Key Configuration Details

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

## Deployment

Deploy with Kustomize:

```bash
kubectl apply -k .
```

Or deploy individual files:

```bash
kubectl apply -f base.yaml -f redis.yaml -f canary.yaml -f loadtester.yaml -f linkerd-metric-templates.yaml -f linkerd-podmonitor-debug.yaml
```

## Canary Progression

The canary will automatically progress through these weights based on success rate metrics:

- 10% → 20% → 30% → 40% → 50% → Promoted

Success rate threshold: **95%**  
Evaluation interval: **30 seconds**  
Max weight: **50%**

## Monitoring

Check canary status:

```bash
kubectl get canary mesh-test-app -n mesh-test
```

View Flagger logs:

```bash
kubectl logs -n linkerd deployment/flagger
```

## Prerequisites

1. **Linkerd** service mesh installed and running
2. **Flagger** deployed in linkerd namespace with proxy bypass configured
3. **Prometheus** operator with kube-prometheus-stack
4. **Linkerd namespace** has injection enabled: `linkerd.io/inject: enabled`

<!-- docgen:begin id=apps/mesh-test-app/k8s:reference scope=apps/mesh-test-app/k8s hash=2d2b6b4f4e7d -->
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
