# GitOps Organization for Linkerd + Flagger + Prometheus

This document outlines the proper organization of monitoring and progressive delivery resources for GitOps deployment.

## Directory Structure

```
dev-lab/
├── infrastructure/
│   └── monitoring/                    # Cross-cutting monitoring infrastructure
│       ├── kustomization.yaml        # Deploys to monitoring namespace
│       ├── prometheus-stack.yaml     # Helm release for kube-prometheus-stack
│       ├── linkerd-servicemonitors.yaml    # Linkerd control plane monitoring
│       ├── linkerd-podmonitor-simple.yaml  # Global Linkerd proxy monitoring
│       ├── flagger-servicemonitor.yaml     # Flagger controller monitoring
│       └── grafana-dashboard-configmap.yaml # Canary deployment dashboard
│
└── apps/
    └── mesh-test-app/
        └── k8s/                       # Application-specific resources
            ├── kustomization.yaml     # Deploys to mesh-test namespace
            ├── base.yaml              # Application deployment & service
            ├── redis.yaml             # Redis dependency
            ├── canary.yaml            # Flagger canary definition
            ├── loadtester.yaml        # Load testing for canary
            ├── linkerd-metric-templates.yaml  # App-specific metric queries
            └── linkerd-podmonitor-debug.yaml  # Detailed proxy monitoring
```

## Resource Ownership

### Infrastructure/Monitoring Namespace
- **ServiceMonitors**: For cross-cutting services (Flagger, Linkerd control plane)
- **PodMonitors**: Global proxy monitoring across all namespaces
- **Grafana Dashboards**: Visualization for canary deployments
- **Prometheus Stack**: Core monitoring infrastructure

### Application Namespace  
- **Canary Definitions**: Application-specific progressive delivery
- **MetricTemplates**: Custom Prometheus queries for canary analysis
- **Application PodMonitors**: Detailed monitoring for specific apps
- **Application Services**: Core application resources

## Deployment Commands

### Deploy Infrastructure (Monitoring)
```bash
cd dev-lab/infrastructure/monitoring
kubectl apply -k .
```

### Deploy Application
```bash  
cd dev-lab/apps/mesh-test-app/k8s
kubectl apply -k .
```

## Key Integration Points

1. **Flagger Metrics**: Exposed via ServiceMonitor in monitoring namespace
2. **Linkerd Metrics**: Collected via PodMonitors for success rate analysis
3. **Grafana Dashboard**: Shows real-time canary progression and health
4. **MetricTemplates**: Define how Flagger evaluates canary success

## Troubleshooting

- **Missing Flagger Metrics**: Check ServiceMonitor in monitoring namespace
- **No Dashboard Data**: Verify ConfigMap labels include `grafana_dashboard: "1"`
- **Canary Analysis Fails**: Check MetricTemplates and Prometheus connectivity
- **Linkerd Metrics Missing**: Verify PodMonitor selector matches proxy pods