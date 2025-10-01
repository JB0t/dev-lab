# Monitoring Infrastructure

This directory contains monitoring configurations for the dev-lab environment, including Linkerd service mesh monitoring, Flagger progressive delivery monitoring, and Grafana dashboards.

## Structure

- `linkerd-servicemonitors.yaml` - ServiceMonitor configurations for Linkerd components
- `linkerd-podmonitor-simple.yaml` - PodMonitor for simplified Linkerd metrics collection
- `flagger-servicemonitor.yaml` - ServiceMonitor for Flagger canary deployment metrics
- `linkerd-canary-dashboard.json` - External Grafana dashboard definition for Linkerd canary deployments
- `kustomization.yaml` - Kustomize configuration with ConfigMapGenerator

## Grafana Dashboard Management

The Linkerd canary dashboard is now externalized as a separate JSON file (`linkerd-canary-dashboard.json`) instead of being embedded in a ConfigMap YAML. This provides several benefits:

### Benefits of External Dashboard File

1. **Easier Editing**: Edit the dashboard JSON directly without YAML escaping
2. **Version Control**: Better diff visualization for dashboard changes
3. **External Tools**: Use Grafana CLI, API, or other tools to import/export dashboards
4. **Validation**: JSON syntax validation is easier than YAML-embedded JSON
5. **Separation of Concerns**: Dashboard definition separate from Kubernetes configuration

### How It Works

The `kustomization.yaml` uses a `configMapGenerator` to create the ConfigMap from the external JSON file:

```yaml
configMapGenerator:
  - name: linkerd-canary-dashboard
    namespace: monitoring
    files:
      - linkerd-canary-dashboard.json
    options:
      labels:
        grafana_dashboard: "1"
        release: kube-prometheus-stack
```

This generates the same ConfigMap that Grafana expects, with the necessary labels for automatic dashboard discovery.

### Updating the Dashboard

To update the dashboard:

1. Edit `linkerd-canary-dashboard.json` directly
2. Test the JSON syntax: `jq . linkerd-canary-dashboard.json`
3. Apply the changes: `kubectl apply -k .`

The ConfigMap will be regenerated with a new hash suffix, and Grafana will automatically reload the dashboard.

### External Access

You can now use external tools to work with the dashboard:

```bash
# Import to Grafana directly
curl -X POST \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @linkerd-canary-dashboard.json \
  http://grafana.example.com/api/dashboards/db

# Validate JSON syntax
jq . linkerd-canary-dashboard.json

# Pretty print and save
jq . linkerd-canary-dashboard.json > formatted-dashboard.json
```

## Dashboard Features

The Linkerd canary dashboard includes:

- **Canary Deployment Status**: Traffic weight distribution and deployment phase
- **Success Rate Monitoring**: Real-time success rate with thresholds
- **Request Rate Metrics**: Requests per second across services
- **mTLS Security**: TLS connection status and certificate monitoring
- **Load Balancing**: Pod-level traffic distribution analysis
- **Performance Metrics**: Response latency P99/P50 percentiles

## Deployment

This monitoring configuration is deployed as part of the GitOps infrastructure:

```bash
# Deploy via Flux (recommended)
kubectl apply -f clusters/dev-lab/dev-lab-kustomizations.yaml

# Deploy directly
kubectl apply -k infrastructure/monitoring/
```