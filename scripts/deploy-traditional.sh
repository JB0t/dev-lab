#!/bin/bash

# Dev Lab Traditional Deployment Script
# Script-based deployment method (post-bootstrap)
# Installs infrastructure components using direct kubectl/helm commands

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

section() {
    echo ""
    echo -e "${PURPLE}=== $1 ===${NC}"
    echo ""
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install Linkerd CLI if needed
install_linkerd_cli() {
    if ! command_exists linkerd; then
        log "Installing Linkerd CLI..."
        curl -sL https://run.linkerd.io/install | sh
        export PATH=$PATH:$HOME/.linkerd2/bin
        
        if ! command_exists linkerd; then
            error "Failed to install Linkerd CLI"
            exit 1
        fi
        success "Linkerd CLI installed"
    fi
}

# Setup Linkerd service mesh
setup_linkerd() {
    section "Setting up Linkerd Service Mesh"
    
    install_linkerd_cli
    
    log "Installing Gateway API CRDs (required for Linkerd)..."
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
    
    log "Waiting for Gateway API CRDs to be ready..."
    kubectl wait --for condition=established --timeout=60s crd/gateways.gateway.networking.k8s.io
    kubectl wait --for condition=established --timeout=60s crd/httproutes.gateway.networking.k8s.io
    
    success "Gateway API CRDs installed successfully"
    
    log "Checking Linkerd pre-flight..."
    if ! linkerd check --pre; then
        error "Linkerd pre-flight checks failed"
        exit 1
    fi
    
    log "Installing Linkerd CRDs..."
    linkerd install --crds | kubectl apply -f -
    
    log "Installing Linkerd control plane..."
    linkerd install | kubectl apply -f -
    
    log "Waiting for Linkerd to be ready..."
    # Wait for deployments to be available
    kubectl wait --for=condition=available deployment -n linkerd --all --timeout=300s
    
    # Run Linkerd health checks
    if ! linkerd check; then
        error "Linkerd health checks failed"
        exit 1
    fi
    
    success "Linkerd control plane installed successfully"
    
    log "Installing Linkerd Viz extension..."
    linkerd viz install | kubectl apply -f -
    
    log "Waiting for Linkerd Viz to be ready..."
    kubectl wait --for=condition=available deployment -n linkerd-viz --all --timeout=300s
    
    if ! linkerd viz check; then
        error "Linkerd Viz health checks failed"
        exit 1
    fi
    
    success "Linkerd Viz installed successfully"
}

# Setup local registry for traditional deployment
setup_registry() {
    section "Setting up Local Container Registry"
    
    log "Creating dev-lab-registry namespace..."
    kubectl create namespace dev-lab-registry --dry-run=client -o yaml | kubectl apply -f -
    
    log "Deploying registry DaemonSet from external config..."
    kubectl apply -f "$PROJECT_ROOT/config/registry/registry-daemonset.yaml"

    # Deploy registry UI
    log "Deploying registry UI from external config..."
    kubectl apply -f "$PROJECT_ROOT/config/registry/registry-ui.yaml"

    # Wait for registry to be ready
    log "Waiting for registry to be ready..."
    kubectl wait --for=condition=ready pod -l app=docker-registry -n dev-lab-registry --timeout=300s
    kubectl wait --for=condition=ready pod -l app=docker-registry-ui -n dev-lab-registry --timeout=300s
    
    # Test registry connectivity
    log "Testing registry connectivity..."
    local timeout=60
    while [[ $timeout -gt 0 ]]; do
        if curl -f http://localhost:5000/v2/ >/dev/null 2>&1; then
            success "Registry is ready at http://localhost:5000"
            break
        fi
        sleep 2
        ((timeout-=2))
    done
    
    if [[ $timeout -le 0 ]]; then
        error "Registry failed to become ready"
        return 1
    fi
    
    success "Local container registry setup complete"
}

# Check if bootstrap was completed
check_bootstrap() {
    section "Checking Bootstrap Prerequisites"
    
    # Check if cluster exists and is accessible
    if ! kubectl cluster-info --context "kind-dev-lab" >/dev/null 2>&1; then
        error "dev-lab cluster not found or not accessible"
        echo ""
        echo "Please run bootstrap first:"
        echo "  ./scripts/bootstrap.sh"
        exit 1
    fi
    success "KinD cluster is accessible"
    
    # Linkerd will be installed by this script
    info "Linkerd will be installed by traditional deployment"
    
    # Registry will be installed by this script
    info "Registry will be installed by traditional deployment"
    
    info "Bootstrap prerequisites verified"
}

# Install NGINX Ingress Controller
install_nginx_ingress() {
    section "Installing NGINX Ingress Controller"
    
    # Check if already installed
    if kubectl get ns ingress-nginx >/dev/null 2>&1; then
        warn "NGINX Ingress already installed, skipping"
        return 0
    fi
    
    log "Installing NGINX Ingress Controller for KinD..."
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/kind/deploy.yaml
    
    # Wait for ingress controller to be ready
    log "Waiting for NGINX ingress controller to be ready..."
    kubectl wait --namespace ingress-nginx \
        --for=condition=ready pod \
        --selector=app.kubernetes.io/component=controller \
        --timeout=300s
    
    success "NGINX Ingress Controller installed"
}

# Deploy monitoring stack using Helm
deploy_monitoring() {
    section "Deploying Monitoring Stack"
    
    # Check if monitoring namespace exists
    if kubectl get ns monitoring >/dev/null 2>&1; then
        warn "Monitoring namespace already exists"
        if kubectl get deployment -n monitoring kube-prometheus-stack-operator >/dev/null 2>&1; then
            warn "Monitoring stack already installed, skipping"
            return 0
        fi
    fi
    
    # Add Helm repositories
    log "Adding Prometheus and Grafana Helm repositories..."
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update
    
    # Create monitoring namespace
    log "Creating monitoring namespace..."
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    
    # Install Prometheus stack with lightweight configuration
    log "Installing Prometheus stack..."
    helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        --values "$PROJECT_ROOT/config/monitoring/prometheus-values.yaml"
        
    # Wait for monitoring stack to be ready
    log "Waiting for monitoring stack to be ready..."
    kubectl wait --for=condition=ready pod -l "app.kubernetes.io/name=kube-prometheus-stack" -n monitoring --timeout=300s
    
    success "Monitoring stack deployed successfully"
}

# Show access information
show_access_info() {
    section "Traditional Deployment Complete"
    
    echo ""
    success "🎉 Dev Lab traditional deployment completed!"
    echo ""
    echo "📊 **Monitoring & Observability:**"
    echo "  • Prometheus:     http://localhost:30090"
    echo "  • Grafana:        http://localhost:30030 (admin/admin123)"
    echo "  • AlertManager:   http://localhost:9093"
    echo "  • Linkerd Viz:    linkerd viz dashboard"
    echo ""
    echo "🐳 **Container Registry:**"
    echo "  • Registry:       http://localhost:5000"
    echo "  • Registry UI:    kubectl port-forward -n dev-lab-registry svc/docker-registry-ui 5001:80"
    echo ""
    echo "🔧 **Useful Commands:**"
    echo "  kubectl get pods -A                   # All pods"
    echo "  linkerd check                         # Service mesh status"
    echo "  linkerd viz stat -n mesh-test         # App traffic stats"
    echo "  kubectl top pods -A                   # Resource usage"
    echo ""
    echo "📝 **Port Forwards (if needed):**"
    echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
    echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
    echo "  linkerd viz dashboard                 # Auto port-forward for Linkerd"
    echo ""
}

# Main function
main() {
    case "${1:-deploy}" in
        "deploy"|"")
            log "Starting traditional deployment..."
            check_bootstrap
            setup_registry
            setup_linkerd
            install_nginx_ingress
            deploy_monitoring
            show_access_info
            ;;
        "registry")
            setup_registry
            ;;
        "linkerd")
            setup_linkerd
            ;;
        "ingress")
            install_nginx_ingress
            ;;
        "monitoring")
            deploy_monitoring
            ;;
        "info")
            show_access_info
            ;;
        "help"|"-h"|"--help")
            echo "Dev Lab Traditional Deployment Script"
            echo ""
            echo "This script deploys infrastructure using direct kubectl/helm commands."
            echo "It includes container registry and Linkerd service mesh installation via CLI."
            echo "It requires bootstrap.sh to have been run first (without registry or Linkerd)."
            echo ""
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  deploy     Complete traditional deployment (default)"
            echo "  registry   Setup local container registry only"
            echo "  linkerd    Install Linkerd service mesh only"
            echo "  ingress    Install NGINX ingress only"
            echo "  monitoring Deploy monitoring stack only"
            echo "  info       Show access information"
            echo "  help       Show this help"
            echo ""
            echo "Prerequisites:"
            echo "  ./scripts/bootstrap.sh    # Must be run first"
            echo ""
            ;;
        *)
            error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Ensure we're in the right directory
cd "$PROJECT_ROOT"

# Run main function
main "$@"