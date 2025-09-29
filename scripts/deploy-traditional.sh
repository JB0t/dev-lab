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
    
    # Check if Linkerd is installed
    if ! kubectl get ns linkerd >/dev/null 2>&1; then
        error "Linkerd not found"
        echo ""
        echo "Please run bootstrap first:"
        echo "  ./scripts/bootstrap.sh"
        exit 1
    fi
    success "Linkerd is installed"
    
    # Check if registry is running
    if ! kubectl get pods -n dev-lab-registry -l app=docker-registry --field-selector=status.phase=Running >/dev/null 2>&1; then
        error "Local registry not running"
        echo ""
        echo "Please run bootstrap first:"
        echo "  ./scripts/bootstrap.sh"
        exit 1
    fi
    success "Local registry is running"
    
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
            install_nginx_ingress
            deploy_monitoring
            show_access_info
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
            echo "It requires bootstrap.sh to have been run first."
            echo ""
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  deploy     Complete traditional deployment (default)"
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