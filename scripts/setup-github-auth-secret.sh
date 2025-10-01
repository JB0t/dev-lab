#!/bin/bash

# GitHub Authentication Secret Setup Script for External Secrets
# This script securely creates the github-auth-secret in the external-secrets namespace

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="external-secrets"
SECRET_NAME="github-auth-secret"

# Functions
log() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠️ $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

info() {
    echo -e "${CYAN}ℹ️ $1${NC}"
}

section() {
    echo ""
    echo -e "${PURPLE}=== $1 ===${NC}"
    echo ""
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check if we can connect to the cluster
    if ! kubectl cluster-info &> /dev/null; then
        error "Cannot connect to Kubernetes cluster"
        echo "Please ensure you have a valid kubeconfig and cluster access"
        exit 1
    fi
    
    # Check if external-secrets namespace exists
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
        warn "Namespace '$NAMESPACE' does not exist"
        info "Creating namespace '$NAMESPACE'..."
        kubectl create namespace "$NAMESPACE"
        success "Namespace '$NAMESPACE' created"
    else
        success "Namespace '$NAMESPACE' exists"
    fi
    
    success "All prerequisites met"
}

# Validate GitHub token format
validate_token() {
    local token="$1"
    
    # Check if token starts with expected prefixes
    # Classic PATs: ghp_, gho_, ghu_, ghs_, ghr_
    # Fine-grained PATs: github_pat_
    if [[ ! "$token" =~ ^(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_) ]]; then
        error "Invalid GitHub token format"
        echo "GitHub tokens should start with:"
        echo "  - Classic PATs: 'ghp_', 'gho_', 'ghu_', 'ghs_', or 'ghr_'"
        echo "  - Fine-grained PATs: 'github_pat_'"
        return 1
    fi
    
    # Detect token type
    if [[ "$token" =~ ^github_pat_ ]]; then
        info "Detected fine-grained Personal Access Token"
        export TOKEN_TYPE="fine-grained"
    else
        info "Detected classic Personal Access Token"
        export TOKEN_TYPE="classic"
    fi
    
    # Check token length (GitHub tokens are typically 40+ characters)
    if [[ ${#token} -lt 20 ]]; then
        error "GitHub token appears to be too short"
        return 1
    fi
    
    success "Token format validation passed"
    return 0
}

# Test GitHub token by making an API call
test_github_token() {
    local token="$1"
    
    log "Testing GitHub token validity..."
    
    # Test the token by calling GitHub API
    local response=$(curl -s -H "Authorization: token $token" \
                          -H "Accept: application/vnd.github.v3+json" \
                          "https://api.github.com/user" 2>/dev/null || echo "")
    
    if [[ -z "$response" ]]; then
        error "Failed to connect to GitHub API"
        return 1
    fi
    
    # Check if the response contains an error
    if echo "$response" | jq -e '.message' &> /dev/null; then
        local message=$(echo "$response" | jq -r '.message')
        error "GitHub API error: $message"
        return 1
    fi
    
    # Check if we got user information
    if echo "$response" | jq -e '.login' &> /dev/null; then
        local username=$(echo "$response" | jq -r '.login')
        success "Token is valid for user: $username"
        
        # Test repository access for fine-grained tokens
        if [[ "${TOKEN_TYPE:-classic}" == "fine-grained" ]]; then
            log "Testing repository access for fine-grained token..."
            local repo_response=$(curl -s -H "Authorization: token $token" \
                                       -H "Accept: application/vnd.github.v3+json" \
                                       "https://api.github.com/repos/jbotstevens/dev-lab" 2>/dev/null || echo "")
            
            if echo "$repo_response" | jq -e '.name' &> /dev/null; then
                success "Fine-grained token has access to dev-lab repository"
                
                # Test Actions secrets access (this will fail gracefully if no access)
                local secrets_response=$(curl -s -H "Authorization: token $token" \
                                              -H "Accept: application/vnd.github.v3+json" \
                                              "https://api.github.com/repos/jbotstevens/dev-lab/actions/secrets" 2>/dev/null || echo "")
                
                if echo "$secrets_response" | jq -e '.secrets' &> /dev/null; then
                    success "Token has access to GitHub Actions Secrets"
                elif echo "$secrets_response" | jq -e '.message' &> /dev/null; then
                    local secrets_message=$(echo "$secrets_response" | jq -r '.message')
                    if [[ "$secrets_message" == *"Must have admin rights"* ]]; then
                        warn "Token may not have sufficient permissions for Actions Secrets"
                        echo "Fine-grained PAT needs 'Actions: Read and Write' permission for the dev-lab repository"
                    else
                        info "Actions Secrets access check: $secrets_message"
                    fi
                fi
            else
                error "Fine-grained token does not have access to dev-lab repository"
                echo "Please ensure the token is scoped to the 'jbotstevens/dev-lab' repository"
                return 1
            fi
        else
            # Check token scopes for classic tokens
            local scopes_header=$(curl -s -I -H "Authorization: token $token" \
                                       -H "Accept: application/vnd.github.v3+json" \
                                       "https://api.github.com/user" 2>/dev/null | \
                                 grep -i "x-oauth-scopes:" || echo "")
            
            if [[ -n "$scopes_header" ]]; then
                local scopes=$(echo "$scopes_header" | cut -d: -f2- | tr -d '\r\n' | sed 's/^ *//')
                info "Classic token scopes: $scopes"
                
                # Check if repo scope is present
                if [[ "$scopes" == *"repo"* ]]; then
                    success "Classic token has required 'repo' scope"
                else
                    warn "Classic token may not have 'repo' scope - this is required for accessing GitHub Actions Secrets"
                    echo "Please ensure your classic token has 'repo' scope or it may not work with External Secrets"
                fi
            fi
        fi
        
        return 0
    else
        error "Unable to verify token validity"
        return 1
    fi
}

# Create or update the secret
create_secret() {
    local token="$1"
    
    log "Creating GitHub authentication secret..."
    
    # Check if secret already exists
    if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &> /dev/null; then
        warn "Secret '$SECRET_NAME' already exists in namespace '$NAMESPACE'"
        echo ""
        echo "Options:"
        echo "1. Update existing secret"
        echo "2. Delete and recreate secret"
        echo "3. Cancel operation"
        echo ""
        read -p "Choose option (1-3): " choice
        
        case $choice in
            1)
                log "Updating existing secret..."
                kubectl patch secret "$SECRET_NAME" -n "$NAMESPACE" \
                    --type='json' \
                    -p="[{\"op\": \"replace\", \"path\": \"/data/token\", \"value\": \"$(echo -n "$token" | base64 -w 0)\"}]"
                success "Secret updated successfully"
                ;;
            2)
                log "Deleting existing secret..."
                kubectl delete secret "$SECRET_NAME" -n "$NAMESPACE"
                log "Creating new secret..."
                kubectl create secret generic "$SECRET_NAME" \
                    --from-literal=token="$token" \
                    -n "$NAMESPACE"
                success "Secret recreated successfully"
                ;;
            3)
                info "Operation cancelled"
                exit 0
                ;;
            *)
                error "Invalid choice"
                exit 1
                ;;
        esac
    else
        # Create new secret
        kubectl create secret generic "$SECRET_NAME" \
            --from-literal=token="$token" \
            -n "$NAMESPACE"
        success "Secret created successfully"
    fi
    
    # Add labels for better organization
    kubectl label secret "$SECRET_NAME" -n "$NAMESPACE" \
        app.kubernetes.io/name=external-secrets \
        app.kubernetes.io/component=authentication \
        app.kubernetes.io/managed-by=dev-lab-setup \
        --overwrite
    
    success "Secret labels updated"
}

# Verify secret creation
verify_secret() {
    log "Verifying secret creation..."
    
    # Check if secret exists
    if ! kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &> /dev/null; then
        error "Secret was not created successfully"
        return 1
    fi
    
    # Check secret type and data
    local secret_info=$(kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json)
    local secret_type=$(echo "$secret_info" | jq -r '.type')
    local has_token=$(echo "$secret_info" | jq -e '.data.token' &> /dev/null && echo "true" || echo "false")
    
    if [[ "$secret_type" == "Opaque" ]] && [[ "$has_token" == "true" ]]; then
        success "Secret verification passed"
        
        # Show secret details (without revealing the token)
        echo ""
        info "Secret Details:"
        kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o custom-columns=\
NAME:.metadata.name,\
TYPE:.type,\
DATA:.data,\
AGE:.metadata.creationTimestamp
        
        return 0
    else
        error "Secret verification failed"
        return 1
    fi
}

# Show next steps
show_next_steps() {
    section "Next Steps"
    
    echo "✅ GitHub authentication secret has been created successfully!"
    echo ""
    echo "🔄 **Deploy External Secrets Infrastructure:**"
    echo "   ./scripts/deploy-gitops.sh"
    echo "   # or for faster development:"
    echo "   ./scripts/force-reconcile-all.sh"
    echo ""
    echo "🔍 **Verify External Secrets Deployment:**"
    echo "   kubectl get pods -n external-secrets"
    echo "   kubectl get clustersecretstore"
    echo ""
    echo "🔐 **Check Linkerd Trust Anchor Secret Sync:**"
    echo "   kubectl get externalsecret -n linkerd"
    echo "   kubectl get secret linkerd-trust-anchor -n linkerd"
    echo ""
    echo "📋 **Generate Trust Anchor Certificates (if not done already):**"
    echo "   ./scripts/generate-linkerd-trust-anchor.sh"
    echo ""
    echo "⚠️ **Security Reminder:**"
    echo "   - Keep your GitHub token secure"
    echo "   - Consider using a dedicated service account token"
    echo "   - Regularly rotate your tokens"
    echo "   - Monitor token usage in GitHub settings"
}

# Main function
main() {
    section "GitHub Authentication Secret Setup for External Secrets"
    
    echo "This script will securely create the github-auth-secret required by"
    echo "External Secrets Operator to access GitHub Actions Secrets."
    echo ""
    
    case "${1:-setup}" in
        "setup")
            check_prerequisites
            
            echo ""
            echo "🔑 **GitHub Personal Access Token Requirements:**"
            echo ""
            echo "📋 **For Fine-Grained PAT (Recommended for dev-lab):**"
            echo "   - Repository: jbotstevens/dev-lab"
            echo "   - Permissions needed:"
            echo "     • Actions: Read and Write (for GitHub Actions Secrets)"
            echo "     • Metadata: Read (basic repository info)"
            echo "   - Token format: github_pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            echo ""
            echo "📋 **For Classic PAT:**"
            echo "   - Scope: 'repo' (full repository access)"
            echo "   - Token format: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
            echo ""
            echo "📖 **How to create a Fine-Grained PAT:**"
            echo "   1. Go to GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens"
            echo "   2. Click 'Generate new token'"
            echo "   3. Set repository to 'jbotstevens/dev-lab'"
            echo "   4. Under Repository permissions:"
            echo "      - Actions: Read and write"
            echo "      - Metadata: Read"
            echo "   5. Copy the generated token"
            echo ""
            echo "📖 **How to create a Classic PAT:**"
            echo "   1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)"
            echo "   2. Click 'Generate new token (classic)'"
            echo "   3. Select 'repo' scope"
            echo "   4. Copy the generated token"
            echo ""
            
            # Prompt for GitHub token (hidden input)
            echo "🔐 Please enter your GitHub Personal Access Token:"
            read -s -p "Token: " github_token
            echo ""
            
            # Validate token format
            if ! validate_token "$github_token"; then
                exit 1
            fi
            
            # Test token validity
            if ! test_github_token "$github_token"; then
                error "Token validation failed"
                exit 1
            fi
            
            # Create the secret
            create_secret "$github_token"
            
            # Verify creation
            verify_secret
            
            # Show next steps
            show_next_steps
            ;;
        "verify")
            check_prerequisites
            verify_secret
            ;;
        "delete")
            log "Deleting GitHub authentication secret..."
            if kubectl delete secret "$SECRET_NAME" -n "$NAMESPACE" 2>/dev/null; then
                success "Secret deleted successfully"
            else
                warn "Secret not found or already deleted"
            fi
            ;;
        "help")
            echo "GitHub Authentication Secret Setup Script"
            echo ""
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  setup    Create or update the GitHub authentication secret (default)"
            echo "  verify   Verify that the secret exists and is properly formatted"
            echo "  delete   Delete the GitHub authentication secret"
            echo "  help     Show this help"
            echo ""
            echo "Examples:"
            echo "  $0               # Interactive setup"
            echo "  $0 setup         # Same as above"
            echo "  $0 verify        # Check if secret exists"
            echo "  $0 delete        # Remove the secret"
            ;;
        *)
            error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Ensure we have jq for JSON parsing
if ! command -v jq &> /dev/null; then
    warn "jq is not installed - some token validation features will be limited"
    echo "Consider installing jq for enhanced token validation"
fi

# Run main function
main "$@"