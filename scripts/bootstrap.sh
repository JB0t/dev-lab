#!/bin/bash

# Dev Lab Bootstrap Script
# Common initialization steps required for both script-based and GitOps deployments
# This script handles: cluster creation and basic setup only

set -euo pipefail

# Configuration
CLUSTER_NAME="dev-lab"
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

# Check prerequisites
check_prerequisites() {
    section "Checking Prerequisites"
    
    local missing_tools=()
    
    # Check required tools
    for tool in docker kubectl helm kind jq; do
        if command_exists "$tool"; then
            success "$tool is installed"
        else
            error "$tool is not installed"
            missing_tools+=("$tool")
        fi
    done
    
    # Check Docker is running
    if docker info >/dev/null 2>&1; then
        success "Docker is running"
    else
        error "Docker is not running"
        missing_tools+=("docker-running")
    fi
    
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        error "Missing required tools: ${missing_tools[*]}"
        info "Please run: $SCRIPT_DIR/install-prerequisites.sh"
        exit 1
    fi
    
    success "All prerequisites met"
}

# Create KinD cluster with proper configuration
create_cluster() {
    section "Creating KinD Cluster"
    
    # Check if cluster already exists
    if kind get clusters | grep -q "^$CLUSTER_NAME$"; then
        warn "Cluster '$CLUSTER_NAME' already exists"
        read -p "Do you want to delete and recreate it? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log "Deleting existing cluster..."
            kind delete cluster --name "$CLUSTER_NAME"
        else
            info "Using existing cluster"
            # Verify cluster is accessible
            if kubectl cluster-info --context "kind-$CLUSTER_NAME" >/dev/null 2>&1; then
                success "Existing cluster is accessible"
                return 0
            else
                error "Existing cluster is not accessible, please delete it manually"
                exit 1
            fi
        fi
    fi
    
    # Ensure kind config exists
    if [[ ! -f "$PROJECT_ROOT/cluster/kind-config.yaml" ]]; then
        error "Kind config not found at $PROJECT_ROOT/cluster/kind-config.yaml"
        exit 1
    fi
    
    log "Creating KinD cluster with configuration..."
    kind create cluster --config "$PROJECT_ROOT/cluster/kind-config.yaml" --wait 300s
    
    # Verify cluster
    if kubectl cluster-info --context "kind-$CLUSTER_NAME" >/dev/null 2>&1; then
        success "Cluster created successfully"
    else
        error "Failed to create cluster"
        exit 1
    fi
    
    # Wait for nodes to be ready
    log "Waiting for all nodes to be ready..."
    kubectl wait --for=condition=Ready nodes --all --timeout=300s
    
    # Display cluster info
    info "Cluster nodes:"
    kubectl get nodes -o wide
}

# NOTE: Registry setup moved to deploy-traditional.sh for script-based deployments
# and to GitOps infrastructure/container-registry/ component for GitOps deployments
setup_registry() {
    info "Registry setup is handled by deployment scripts:"
    info "  • Script-based: ./scripts/deploy-traditional.sh"
    info "  • GitOps: infrastructure/container-registry/ component"
}

# Setup metrics server
setup_metrics_server() {
    section "Setting up Metrics Server"
    
    log "Installing metrics-server..."
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    
    # Patch metrics-server for KinD
    log "Patching metrics-server for KinD compatibility..."
    kubectl patch deployment metrics-server -n kube-system --type='json' \
        -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
    
    # Wait for metrics-server to be ready
    log "Waiting for metrics-server to be ready..."
    kubectl wait --for=condition=available deployment/metrics-server -n kube-system --timeout=300s
    
    success "Metrics server deployed"
}

# Display bootstrap completion info
show_bootstrap_info() {
    section "Bootstrap Complete"
    
    echo ""
    success " Dev Lab bootstrap completed successfully!"
    echo ""
    echo " **Core Infrastructure Ready:**"
    echo "  • KinD cluster with proper node labels"
    echo "  • Metrics server for autoscaling"
    echo ""
    echo " **Next Steps - Choose Your Deployment Method:**"
    echo ""
    echo " **Script-based deployment (traditional):**"
    echo "  ./scripts/deploy-traditional.sh"
    echo "  • Installs local registry via config files"
    echo "  • Installs Linkerd service mesh via CLI"
    echo "  • Installs monitoring via Helm commands"
    echo "  • Installs NGINX ingress via kubectl"
    echo "  • Manual app deployment"
    echo ""
    echo " **GitOps deployment (automated):**"
    echo "  ./scripts/deploy-gitops.sh"
    echo "  • Installs Flux controllers"
    echo "  • Sets up SSH deploy key"
    echo "  • Automatic registry + Linkerd + infrastructure + app deployment via Git"
    echo ""
    echo " **Verification Commands:**"
    echo "  kubectl get nodes                     # Check cluster"
    echo "  kubectl top nodes                    # Check metrics server"
    echo ""
}

# Cleanup function
cleanup() {
    log "Cleaning up bootstrap process..."
}

# Main bootstrap function
main() {
    case "${1:-bootstrap}" in
        "bootstrap"|"setup"|"")
            log "Starting Dev Lab bootstrap process..."
            check_prerequisites
            create_cluster
            setup_metrics_server
            show_bootstrap_info
            ;;
        "cluster")
            create_cluster
            ;;
        "registry")
            setup_registry
            ;;
        "metrics")
            setup_metrics_server
            ;;
        "help"|"-h"|"--help")
            echo "Dev Lab Bootstrap Script"
            echo ""
            echo "This script handles common initialization for both deployment methods:"
            echo "  • KinD cluster creation with proper configuration"
            echo "  • Metrics server installation"
            echo ""
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  bootstrap  Complete bootstrap process (default)"
            echo "  cluster    Create KinD cluster only"
            echo "  registry   Show registry setup info (now in deployment scripts)"
            echo "  metrics    Setup metrics server only"
            echo "  help       Show this help"
            echo ""
            echo "After bootstrap, choose your deployment method:"
            echo "  ./scripts/deploy-traditional.sh  # Script-based deployment (includes registry + Linkerd)"
            echo "  ./scripts/deploy-gitops.sh       # GitOps deployment (registry + Linkerd via Flux)"
            echo ""
            ;;
        *)
            error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Handle interruption
trap cleanup SIGINT SIGTERM

# Ensure we're in the right directory
cd "$PROJECT_ROOT"

# Run main function
main "$@"