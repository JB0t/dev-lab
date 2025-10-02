#!/bin/bash

echo "🚀 Force reconciling all Flux components for faster development cycle..."
echo ""

# First reconcile the git source
echo "📡 Reconciling Git source..."
flux reconcile source git dev-lab-repo -n flux-system

echo ""
echo "🔧 Reconciling all infrastructure Kustomizations..."

# Reconcile all infrastructure kustomizations in dependency order
KUSTOMIZATIONS=(
    "dev-lab-base"
    "dev-lab-prometheus" 
    "dev-lab-registry"
    "dev-lab-cert-manager"
    "dev-lab-linkerd-certs"
    "dev-lab-service-mesh"
    "dev-lab-networking"
    "dev-lab-flagger"
    "dev-lab-monitoring"
    "dev-lab-apps"
)

for kustomization in "${KUSTOMIZATIONS[@]}"; do
    echo "  → Reconciling $kustomization..."
    flux reconcile kustomization "$kustomization" -n flux-system
done

echo ""
echo "⚡ Force reconciling Helm components..."

# Force reconcile helm repositories
echo "  → Reconciling Helm repositories..."
flux reconcile source helm linkerd -n linkerd 2>/dev/null || true
flux reconcile source helm jetstack-linkerd -n linkerd 2>/dev/null || true
flux reconcile source helm flagger -n flux-system 2>/dev/null || true
flux reconcile source helm prometheus-community -n monitoring 2>/dev/null || true
flux reconcile source helm grafana -n monitoring 2>/dev/null || true

# Force reconcile helm releases
echo "  → Reconciling Helm releases..."
flux reconcile helmrelease linkerd-crds -n linkerd 2>/dev/null || true
flux reconcile helmrelease linkerd-control-plane -n linkerd 2>/dev/null || true
flux reconcile helmrelease linkerd-viz -n linkerd-viz 2>/dev/null || true
flux reconcile helmrelease flagger -n flux-system 2>/dev/null || true
flux reconcile helmrelease kube-prometheus-stack -n monitoring 2>/dev/null || true

echo ""
echo "✅ All reconciliations triggered! Infrastructure should now reconcile much faster."
echo "💡 Check status with: flux get all"
echo "📊 Monitor reconciliation with: watch 'flux get kustomizations'"