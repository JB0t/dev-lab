#!/bin/bash

# Dev Lab GitOps Deployment Script
# GitOps deployment method (post-bootstrap)
# Sets up Flux CD for automated infrastructure and application deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
KEY_PATH="/tmp/flux-deploy-key"
REPO_URL="ssh://git@github.com/jbotstevens/notes.git"

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

# Install Flux CLI if not present
install_flux_cli() {
    if ! command -v flux >/dev/null 2>&1; then
        log "Installing Flux CLI..."
        curl -s https://fluxcd.io/install.sh | sudo bash
        success "Flux CLI installed"
    else
        success "Flux CLI is available"
    fi
}

# Install Flux controllers
install_flux_controllers() {
    section "Installing Flux Controllers"
    
    # Check if flux-system namespace already exists
    if kubectl get ns flux-system >/dev/null 2>&1; then
        warn "Flux controllers may already be installed"
        if kubectl get deployment -n flux-system source-controller >/dev/null 2>&1; then
            success "Flux controllers already installed"
            return 0
        fi
    fi
    
    log "Installing Flux controllers..."
    flux install
    
    # Wait for controllers to be ready
    log "Waiting for Flux controllers to be ready..."
    kubectl wait --for=condition=available deployment --all -n flux-system --timeout=300s
    
    success "Flux controllers installed and ready"
}

# Generate SSH deploy key
generate_deploy_key() {
    section "Setting up SSH Deploy Key"
    
    if [[ -f "${KEY_PATH}" ]]; then
        warn "Deploy key already exists. Removing old key..."
        rm -f "${KEY_PATH}" "${KEY_PATH}.pub"
    fi
    
    log "Generating new SSH key pair..."
    ssh-keygen -t ed25519 -f "${KEY_PATH}" -N "" -C "flux-dev-lab-$(date +%Y%m%d)"
    
    if [[ ! -f "${KEY_PATH}" ]]; then
        error "Failed to generate SSH key"
        exit 1
    fi
    
    success "SSH key pair generated"
}

# Create Flux system secret
create_flux_secret() {
    log "Creating flux-system secret with SSH deploy key..."
    
    # Delete existing secret if it exists
    kubectl delete secret flux-system-auth -n flux-system --ignore-not-found=true
    
    # Create new secret with SSH key
    kubectl create secret generic flux-system-auth \
        --from-file=identity="${KEY_PATH}" \
        --from-file=identity.pub="${KEY_PATH}.pub" \
        --from-literal=known_hosts="$(ssh-keyscan github.com)" \
        -n flux-system
    
    # Label the secret
    kubectl label secret flux-system-auth -n flux-system app.kubernetes.io/part-of=flux
    
    success "flux-system-auth secret created"
}

# Display deploy key for GitHub setup
show_deploy_key() {
    log "Add this public key as a deploy key to your GitHub repository:"
    echo ""
    echo -e "${CYAN}Repository:${NC} https://github.com/jbotstevens/dev-lab"
    echo -e "${CYAN}Settings → Deploy keys → Add deploy key${NC}"
    echo ""
    echo -e "${YELLOW}Public Key:${NC}"
    echo "----------------------------------------"
    cat "${KEY_PATH}.pub"
    echo "----------------------------------------"
    echo ""
    warn "Make sure to:"
    echo "  1. Give the key a descriptive title (e.g., 'flux-dev-lab-$(date +%Y%m%d)')"
    echo "  2. Paste the public key above"
    echo "  3. Leave 'Allow write access' UNCHECKED (read-only)"
    echo "  4. Click 'Add key'"
    echo ""
    echo -e "${BLUE}Press any key when you've added the deploy key to GitHub...${NC}"
    read -n 1 -s
}

# Create GitRepository source
create_git_source() {
    section "Creating Git Source"
    
    log "Creating GitRepository source from external config..."
    # Update the repository URL in the template
    sed "s|url: ssh://git@github.com/jbotstevens/notes.git|url: ${REPO_URL}|" \
        "$PROJECT_ROOT/config/gitops/git-repository.yaml" | kubectl apply -f -

    # Wait for GitRepository to sync
    log "Waiting for GitRepository to sync..."
    sleep 10
    
    if kubectl wait --for=condition=ready gitrepository dev-lab-repo -n flux-system --timeout=120s; then
        success "GitRepository synced successfully"
    else
        warn "GitRepository may not be ready yet. Continuing..."
    fi
}

# Apply Git-managed kustomizations
apply_git_kustomizations() {
    section "Applying Git-Managed Kustomizations"
    
    log "Applying Kustomizations from Git repository..."
    
    # Apply the cluster-specific kustomizations that are managed in Git
    kubectl apply -f "$PROJECT_ROOT/clusters/dev-lab/dev-lab-kustomizations.yaml"
    
    success "Git-managed Kustomizations applied"
    info "Infrastructure and applications will be deployed automatically from Git"
}

# Wait for deployment completion
wait_for_deployment() {
    section "Waiting for GitOps Deployment"
    
    log "Monitoring infrastructure deployment..."
    echo ""
    info "This may take several minutes as Flux deploys:"
    echo "  • NGINX Ingress Controller"
    echo "  • Prometheus Monitoring Stack"
    echo "  • Container Registry UI"
    echo "  • Sample Applications"
    echo ""
    
    # Monitor infrastructure kustomization
    local timeout=900  # 15 minutes
    local elapsed=0
    local interval=10
    
    while [[ $elapsed -lt $timeout ]]; do
        local infra_ready=$(kubectl get kustomization dev-lab-infrastructure -n flux-system -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
        local apps_ready=$(kubectl get kustomization dev-lab-apps -n flux-system -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
        
        echo -ne "\r${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} Infrastructure: ${infra_ready}, Apps: ${apps_ready} (${elapsed}s elapsed)\n"
        
        if [[ "$infra_ready" == "True" && "$apps_ready" == "True" ]]; then
            echo ""
            success "GitOps deployment completed successfully!"
            return 0
        fi
        
        sleep $interval
        ((elapsed+=interval))
    done
    
    echo ""
    warn "Deployment is taking longer than expected, but may still be in progress"
    warn "Use 'flux get kustomizations -A' to monitor status"
}

# Show GitOps status and access info
show_gitops_info() {
    section "GitOps Deployment Complete"
    
    echo ""
    success "🎉 Dev Lab GitOps deployment setup complete!"
    echo ""
    echo "🔄 **GitOps Status:**"
    flux get all -A | head -20
    echo ""
    echo "📊 **Access Information:**"
    echo "  • Prometheus:     kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
    echo "  • Grafana:        kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 (admin/admin123)"
    echo "  • AlertManager:   kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093"
    echo "  • Linkerd Viz:    linkerd viz dashboard"
    echo "  • Registry UI:    kubectl port-forward -n dev-lab-registry svc/docker-registry-ui 5001:80"
    echo ""
    echo "🔧 **GitOps Monitoring Commands:**"
    echo "  flux get all -A                      # Overview of all Flux resources"
    echo "  flux logs --all-namespaces          # Controller logs"
    echo "  watch flux get kustomizations -A    # Watch reconciliation"
    echo "  kubectl get events -n flux-system   # System events"
    echo ""
    echo "🚀 **Sample Application (once apps are deployed):**"
    echo "  • Add to /etc/hosts: 127.0.0.1 sample-app.local"
    echo "  • Access at: http://sample-app.local"
    echo ""
    echo "📝 **Notes:**"
    echo "  • Infrastructure and apps are automatically deployed from Git"
    echo "  • Changes to dev-lab/ directory will be reconciled automatically"
    echo "  • Use Git commits to manage deployments"
    echo ""
}

# Cleanup function
cleanup() {
    log "Cleaning up temporary files..."
    rm -f "${KEY_PATH}" "${KEY_PATH}.pub"
}

# Main function
main() {
    case "${1:-deploy}" in
        "deploy"|"")
            log "Starting GitOps deployment..."
            check_bootstrap
            install_flux_cli
            install_flux_controllers
            generate_deploy_key
            create_flux_secret
            show_deploy_key
            create_git_source
            apply_git_kustomizations
            wait_for_deployment
            show_gitops_info
            ;;
        "flux")
            install_flux_cli
            install_flux_controllers
            ;;
        "key")
            generate_deploy_key
            show_deploy_key
            ;;
        "sources")
            create_git_source
            ;;
        "kustomizations")
            apply_git_kustomizations
            ;;
        "status")
            section "GitOps Status"
            flux get all -A
            ;;
        "info")
            show_gitops_info
            ;;
        "help"|"-h"|"--help")
            echo "Dev Lab GitOps Deployment Script"
            echo ""
            echo "This script sets up Flux CD for automated deployment from Git."
            echo "It requires bootstrap.sh to have been run first."
            echo ""
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  deploy        Complete GitOps deployment (default)"
            echo "  flux          Install Flux controllers only"
            echo "  key           Generate and show SSH deploy key"
            echo "  sources       Create Git sources only"
            echo "  kustomizations Apply Git-managed kustomizations only"
            echo "  status        Show GitOps deployment status"
            echo "  info          Show access information"
            echo "  help          Show this help"
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

# Trap cleanup on exit
trap cleanup EXIT

# Ensure we're in the right directory
cd "$PROJECT_ROOT"

# Run main function
main "$@"