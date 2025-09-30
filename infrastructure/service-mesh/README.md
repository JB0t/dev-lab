# GitOps Linkerd Implementation

This directory contains a complete GitOps-friendly Linkerd service mesh implementation inspired by [stefanprodan/gitops-linkerd](https://github.com/stefanprodan/gitops-linkerd).

## Production Considerations

### **Certificate Management**

Linkerd deploys a dedicated isolated cert-manager component to its namespace to facilitate mTLS certificate management.

## Architecture

The implementation follows a layered approach with proper dependency management:

```
1. cert-manager (certificate lifecycle management)
2. Linkerd CRDs (custom resource definitions)
3. Linkerd Control Plane (with cert-manager generated certificates)
4. Linkerd Viz (observability extension)
```

## Components

### Trust Anchor Certificate
- **File**: `ca.crt` and `ca.key`
- **Purpose**: Root certificate for Linkerd's identity system
- **Generated with**: `openssl req -x509 -new -newkey rsa:4096 ...`
- **Lifecycle**: Pre-generated and stored in Git (valid for 10 years)

### Kustomize Secret Generator
- **Purpose**: Creates `linkerd-trust-anchor` secret from ca.crt/ca.key files
- **Usage**: Referenced by the control plane Helm chart via `valuesFrom`

### Helm Charts
- **linkerd-crds**: Installs Linkerd Custom Resource Definitions
- **linkerd-control-plane**: Installs the main Linkerd service mesh
- **linkerd-viz**: Installs observability dashboard and tools

### cert-manager Integration
- **Issuer**: Creates CA issuer from the trust anchor secret
- **Certificate**: Generates identity issuer certificate for Linkerd

## Key Features

✅ **Fully Declarative**: No CLI tools required after initial certificate generation  
✅ **Proper Dependencies**: cert-manager → Linkerd CRDs → Control Plane → Viz  
✅ **Certificate Automation**: cert-manager handles identity issuer lifecycle  
✅ **GitOps Native**: All configuration stored in Git with Flux reconciliation  
✅ **Dev Optimized**: Resource-constrained settings for local development  

## Deployment Flow

1. **Bootstrap** creates the KinD cluster and basic infrastructure
2. **Flux** deploys cert-manager first
3. **cert-manager** processes the trust anchor and creates issuer
4. **Linkerd CRDs** are installed via Helm
5. **Linkerd Control Plane** is installed with certificate injection
6. **Linkerd Viz** is deployed for observability

## Verification

```bash
# Check Flux reconciliation
flux get helmreleases -A

# Check Linkerd installation
kubectl get pods -n linkerd
kubectl get pods -n linkerd-viz

# Check certificates
kubectl get certificates -n linkerd
kubectl describe certificate linkerd-identity-issuer -n linkerd

# Access Linkerd dashboard
kubectl port-forward -n linkerd-viz svc/web 8084:8084
```

## Differences from CLI Installation

| Aspect | CLI (`linkerd install`) | GitOps (This Implementation) |
|--------|------------------------|------------------------------|
| Certificates | Generated dynamically | Pre-generated + cert-manager |
| Deployment | Imperative commands | Declarative manifests |
| Updates | Manual CLI commands | Automatic Git reconciliation |
| Rollbacks | Manual process | Git revert + Flux sync |
| Observability | Limited to CLI | Full GitOps visibility |

## Troubleshooting

### Certificate Issues
```bash
# Check trust anchor secret
kubectl get secret linkerd-trust-anchor -n linkerd -o yaml

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager
```

### Helm Release Issues
```bash
# Check Helm release status
helm list -n linkerd
flux get helmreleases -n linkerd

# Check Flux logs
flux logs --level=debug
```

### Control Plane Issues
```bash
# Check Linkerd status (requires CLI)
linkerd check

# Check pod logs
kubectl logs -n linkerd deployment/linkerd-destination
kubectl logs -n linkerd deployment/linkerd-identity
kubectl logs -n linkerd deployment/linkerd-proxy-injector
```

## Benefits over CLI Approach

1. **Reproducible**: Exact same installation every time
2. **Auditable**: All changes tracked in Git
3. **Rollback-friendly**: Git history provides rollback capability
4. **Multi-environment**: Easy to replicate across environments
5. **Team-friendly**: No need for team members to have Linkerd CLI
6. **Automated**: Zero manual intervention after initial setup