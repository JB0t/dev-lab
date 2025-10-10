# Platform Monitoring Infrastructure

This directory contains platform-level monitoring configurations for the dev-lab environment, focusing on application-layer monitoring and Grafana dashboards.

## Architecture

The monitoring stack is now split across layers for better separation of concerns:

- **Service Mesh Layer** (External repo): Core Linkerd monitoring (ServiceMonitors, PodMonitors)
- **Platform Monitoring** (This directory): Application dashboards and Flagger monitoring
- **Application Layer** (Individual apps): App-specific enhanced monitoring

## Structure

- `flagger-servicemonitor.yaml` - ServiceMonitor for Flagger progressive delivery metrics
- `linkerd-canary-dashboard.json` - Grafana dashboard for individual Linkerd canary deployments
- `multi-app-canary-dashboard.json` - Grafana dashboard for multi-application canary monitoring
- `kustomization.yaml` - Kustomize configuration with ConfigMapGenerator

## Grafana Dashboard Management

Dashboards are externalized as separate JSON files for better maintainability:

### Benefits of External Dashboard Files

1. **Easier Editing**: Edit dashboard JSON directly without YAML escaping
2. **Version Control**: Better diff visualization for dashboard changes
3. **External Tools**: Use Grafana CLI, API, or other tools to import/export dashboards
4. **Validation**: JSON syntax validation is easier than YAML-embedded JSON
5. **Separation of Concerns**: Dashboard definition separate from Kubernetes configuration

### How It Works

The `kustomization.yaml` uses a `configMapGenerator` to create ConfigMaps from external JSON files:

```yaml
configMapGenerator:
  - name: dashboards
    namespace: monitoring
    files:
      - linkerd-canary-dashboard.json
      - multi-app-canary-dashboard.json
    options:
      labels:
        grafana_dashboard: "1"
        release: kube-prometheus-stack
```

This generates ConfigMaps that Grafana automatically discovers and loads.

### Available Dashboards

1. **linkerd-canary-dashboard.json**: Individual service canary deployment monitoring
2. **multi-app-canary-dashboard.json**: Cross-application canary deployment overview

### Updating Dashboards

To update dashboards:

1. Edit the JSON files directly
2. Test JSON syntax: `jq . <dashboard-file>.json`
3. Apply changes: `kubectl apply -k .`

## Dashboard Features

### Multi-App Canary Dashboard
- **Dynamic Application Discovery**: Automatically finds canary deployments
- **Cross-App Comparison**: Compare metrics across different services
- **Template Variables**: Filter by namespace, application, or deployment
- **Unified View**: Single dashboard for all canary operations

### Individual Canary Dashboard
- **Detailed Service Metrics**: Deep dive into individual service performance
- **Canary vs Primary**: Side-by-side comparison of deployments
- **Success Rate Monitoring**: Real-time success rate with thresholds
- **mTLS Security**: TLS connection status and certificate monitoring

## Deployment

This monitoring configuration is deployed as part of the GitOps infrastructure:

```bash
# Deploy via Flux (recommended)
kubectl apply -f clusters/dev-lab/dev-lab-kustomizations.yaml

# Deploy directly
kubectl apply -k infrastructure/monitoring/
```
