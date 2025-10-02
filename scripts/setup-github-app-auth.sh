#!/bin/bash

# GitHub App Setup Script for External Secrets
# This script helps you set up GitHub App authentication for external-secrets

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

# GitHub App setup instructions
show_github_app_setup() {
    section "GitHub App Setup Instructions"
    
    echo "To use external-secrets with GitHub Actions Secrets, you need to create a GitHub App:"
    echo ""
    echo -e "${CYAN}1. Create GitHub App:${NC}"
    echo "   • Go to: https://github.com/settings/apps"
    echo "   • Click 'New GitHub App'"
    echo "   • App name: 'dev-lab-external-secrets'"
    echo "   • Homepage URL: 'https://github.com/jbotstevens/dev-lab'"
    echo "   • Webhook: Uncheck 'Active'"
    echo ""
    echo -e "${CYAN}2. Set Permissions:${NC}"
    echo "   • Repository permissions:"
    echo "     - Actions: Read (to access repository workflows)"
    echo "     - Secrets: Read (to access repository secrets)"
    echo "     - Metadata: Read (basic repository access)"
    echo "   • Account permissions: None needed"
    echo ""
    echo -e "${CYAN}3. Generate Private Key:${NC}"
    echo "   • Scroll down to 'Private keys'"
    echo "   • Click 'Generate a private key'"
    echo "   • Download the .pem file"
    echo ""
    echo -e "${CYAN}4. Install App:${NC}"
    echo "   • Go to 'Install App' tab"
    echo "   • Install on your account"
    echo "   • Select 'Only select repositories'"
    echo "   • Choose 'jbotstevens/dev-lab'"
    echo ""
    echo -e "${CYAN}5. Get Installation ID:${NC}"
    echo "   • After installation, note the URL"
    echo "   • URL format: https://github.com/settings/installations/INSTALLATION_ID"
    echo "   • The number at the end is your Installation ID"
    echo ""
    echo -e "${YELLOW}Press any key when you've completed the GitHub App setup...${NC}"
    read -n 1 -s
}

# Get GitHub App details from user
get_github_app_details() {
    section "GitHub App Configuration"
    
    echo "Please enter your GitHub App details:"
    echo ""
    
    # Get App ID
    while true; do
        read -p "GitHub App ID: " APP_ID
        if [[ "$APP_ID" =~ ^[0-9]+$ ]]; then
            break
        else
            error "App ID must be a number"
        fi
    done
    
    # Get Installation ID
    while true; do
        read -p "GitHub App Installation ID: " INSTALLATION_ID
        if [[ "$INSTALLATION_ID" =~ ^[0-9]+$ ]]; then
            break
        else
            error "Installation ID must be a number"
        fi
    done
    
    # Get private key file path
    while true; do
        echo ""
        read -p "Path to GitHub App private key (.pem file): " PRIVATE_KEY_PATH
        if [[ -f "$PRIVATE_KEY_PATH" ]]; then
            break
        else
            error "Private key file not found: $PRIVATE_KEY_PATH"
        fi
    done
    
    log "GitHub App details collected successfully"
}

# Update configuration files with GitHub App details
update_config_files() {
    section "Updating Configuration Files"
    
    # Update SecretStore
    log "Updating SecretStore configuration..."
    sed -i "s/appID: 12345/appID: $APP_ID/" "$PROJECT_ROOT/infrastructure/external-secrets-config/github-secret-store.yaml"
    sed -i "s/installationID: 67890/installationID: $INSTALLATION_ID/" "$PROJECT_ROOT/infrastructure/external-secrets-config/github-secret-store.yaml"
    
    # Update ClusterSecretStore
    log "Updating ClusterSecretStore configuration..."
    sed -i "s/appID: 12345/appID: $APP_ID/" "$PROJECT_ROOT/infrastructure/external-secrets-config/github-cluster-secret-store.yaml"
    sed -i "s/installationID: 67890/installationID: $INSTALLATION_ID/" "$PROJECT_ROOT/infrastructure/external-secrets-config/github-cluster-secret-store.yaml"
    
    success "Configuration files updated with GitHub App details"
}

# Create Kubernetes secret with GitHub App private key
create_github_app_secret() {
    section "Creating GitHub App Secret"
    
    log "Creating Kubernetes secret with GitHub App private key..."
    
    # Ensure external-secrets namespace exists
    kubectl create namespace external-secrets --dry-run=client -o yaml | kubectl apply -f -
    
    # Delete existing secret if it exists
    kubectl delete secret github-app-secret -n external-secrets --ignore-not-found=true
    
    # Create new secret with private key
    kubectl create secret generic github-app-secret \
        --from-file=private-key="$PRIVATE_KEY_PATH" \
        -n external-secrets
    
    # Label the secret
    kubectl label secret github-app-secret -n external-secrets app.kubernetes.io/part-of=external-secrets
    
    success "GitHub App secret created successfully"
}

# Test GitHub App configuration
test_github_app() {
    section "Testing GitHub App Configuration"
    
    log "Testing if GitHub App can access repository..."
    
    # Try to apply the SecretStore manually to test
    if kubectl apply -f "$PROJECT_ROOT/infrastructure/external-secrets-config/github-secret-store.yaml" --dry-run=server; then
        success "SecretStore configuration is valid"
    else
        error "SecretStore configuration failed validation"
        return 1
    fi
    
    if kubectl apply -f "$PROJECT_ROOT/infrastructure/external-secrets-config/github-cluster-secret-store.yaml" --dry-run=server; then
        success "ClusterSecretStore configuration is valid"
    else
        error "ClusterSecretStore configuration failed validation"
        return 1
    fi
    
    info "GitHub App configuration appears to be correct"
}

# Show next steps
show_next_steps() {
    section "Next Steps"
    
    echo ""
    success "GitHub App setup completed!"
    echo ""
    echo -e "${CYAN}To deploy the external-secrets configuration:${NC}"
    echo "  flux reconcile source git dev-lab-repo"
    echo "  flux reconcile kustomization dev-lab-external-secrets-config"
    echo ""
    echo -e "${CYAN}To test external-secrets:${NC}"
    echo "  kubectl get secretstores -n external-secrets"
    echo "  kubectl get clustersecretstores"
    echo "  kubectl describe secretstore github-secret-store -n external-secrets"
    echo ""
    echo -e "${CYAN}To verify GitHub App access:${NC}"
    echo "  kubectl logs -n external-secrets deployment/external-secrets"
    echo ""
    echo -e "${YELLOW}Note: Make sure your GitHub App has the correct permissions:${NC}"
    echo "  • Repository permissions: Actions (Read), Secrets (Read), Metadata (Read)"
    echo "  • Installed on the jbotstevens/dev-lab repository"
    echo ""
}

# Main function
main() {
    case "${1:-setup}" in
        "setup"|"")
            log "Starting GitHub App setup for external-secrets..."
            show_github_app_setup
            get_github_app_details
            update_config_files
            create_github_app_secret
            test_github_app
            show_next_steps
            ;;
        "test")
            test_github_app
            ;;
        "help"|"-h"|"--help")
            echo "GitHub App Setup Script for External Secrets"
            echo ""
            echo "This script helps you configure external-secrets to use GitHub App authentication"
            echo "for accessing GitHub Actions Secrets."
            echo ""
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  setup     Complete GitHub App setup (default)"
            echo "  test      Test GitHub App configuration"
            echo "  help      Show this help"
            echo ""
            echo "Prerequisites:"
            echo "  • GitHub App created with appropriate permissions"
            echo "  • GitHub App installed on the target repository"
            echo "  • Private key file downloaded"
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