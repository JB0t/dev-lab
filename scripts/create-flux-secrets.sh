#!/bin/bash

# Quick script to create Flux secrets from SSH keys
# This creates the Kubernetes secrets needed for GitRepository authentication

set -euo pipefail

KEY_PATH="/tmp/flux-deploy-key"
SERVICE_MESH_KEY_PATH="/tmp/flux-service-mesh-layer-key"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"
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

# Check if keys exist, generate if not
ensure_keys_exist() {
    local need_generate=false
    
    if [[ ! -f "${KEY_PATH}" || ! -f "${KEY_PATH}.pub" ]]; then
        log "Main repository keys not found, generating..."
        ssh-keygen -t ed25519 -f "${KEY_PATH}" -N "" -C "flux-dev-lab-$(date +%Y%m%d)"
        need_generate=true
    fi
    
    if [[ ! -f "${SERVICE_MESH_KEY_PATH}" || ! -f "${SERVICE_MESH_KEY_PATH}.pub" ]]; then
        log "Service mesh layer keys not found, generating..."
        ssh-keygen -t ed25519 -f "${SERVICE_MESH_KEY_PATH}" -N "" -C "flux-service-mesh-layer-$(date +%Y%m%d)"
        need_generate=true
    fi
    
    if [[ "$need_generate" == "true" ]]; then
        warn "New keys generated! You'll need to add these to GitHub:"
        echo ""
        echo "=== MAIN REPOSITORY ==="
        echo "Repository: https://github.com/jbotstevens/dev-lab"
        echo "Public Key:"
        cat "${KEY_PATH}.pub"
        echo ""
        echo "=== SERVICE MESH LAYER REPOSITORY ==="
        echo "Repository: https://github.com/amelcocloud/flux-service-mesh-layer"
        echo "Public Key:"
        cat "${SERVICE_MESH_KEY_PATH}.pub"
        echo ""
    fi
}

# Create main repository secret
create_main_secret() {
    log "Creating dev-lab-repo secret..."
    
    # Delete existing secret if it exists
    kubectl delete secret dev-lab-repo -n flux-system --ignore-not-found=true
    
    # Create new secret with SSH key
    kubectl create secret generic dev-lab-repo \
        --from-file=identity="${KEY_PATH}" \
        --from-file=identity.pub="${KEY_PATH}.pub" \
        --from-literal=known_hosts="$(ssh-keyscan github.com)" \
        -n flux-system
    
    # Label the secret
    kubectl label secret dev-lab-repo -n flux-system app.kubernetes.io/part-of=flux
    
    success "dev-lab-repo secret created"
}

# Create service mesh layer secret
create_service_mesh_secret() {
    log "Creating flux-service-mesh-layer secret..."
    
    # Delete existing secret if it exists
    kubectl delete secret flux-service-mesh-layer -n flux-system --ignore-not-found=true
    
    # Create new secret with SSH key
    kubectl create secret generic flux-service-mesh-layer \
        --from-file=identity="${SERVICE_MESH_KEY_PATH}" \
        --from-file=identity.pub="${SERVICE_MESH_KEY_PATH}.pub" \
        --from-literal=known_hosts="$(ssh-keyscan github.com)" \
        -n flux-system
    
    # Label the secret
    kubectl label secret flux-service-mesh-layer -n flux-system app.kubernetes.io/part-of=flux
    
    success "flux-service-mesh-layer secret created"
}

# Check prerequisites
check_prerequisites() {
    # Check if cluster is accessible
    if ! kubectl cluster-info >/dev/null 2>&1; then
        error "Kubernetes cluster not accessible"
        exit 1
    fi
    
    # Check if flux-system namespace exists
    if ! kubectl get namespace flux-system >/dev/null 2>&1; then
        warn "flux-system namespace doesn't exist, creating..."
        kubectl create namespace flux-system
    fi
    
    success "Prerequisites checked"
}

# Cleanup function
cleanup() {
    log "Cleaning up temporary files..."
    rm -f "${KEY_PATH}" "${KEY_PATH}.pub"
    rm -f "${SERVICE_MESH_KEY_PATH}" "${SERVICE_MESH_KEY_PATH}.pub"
}

# Main function
main() {
    echo "Creating Flux SSH Secrets"
    echo "=============================="
    
    check_prerequisites
    ensure_keys_exist
    create_main_secret
    create_service_mesh_secret
    
    echo ""
    success "All Flux secrets created successfully!"
    echo ""
    log "You can now create GitRepository sources:"
    echo "  kubectl apply -f config/gitops/git-repository.yaml"
    echo "  kubectl apply -f config/gitops/service-mesh-layer-repository.yaml"
    echo ""
    log "Or run the full deployment:"
    echo "  ./scripts/deploy-gitops.sh sources"
    echo "  ./scripts/deploy-gitops.sh kustomizations"
}

# Trap cleanup on exit
trap cleanup EXIT

# Run main function
main "$@"