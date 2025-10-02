#!/bin/bash

# Linkerd Trust Anchor Certificate Generator and GitHub Secrets Manager
# This script generates a new trust anchor certificate for Linkerd and stores it in GitHub Secrets

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_OWNER="jbotstevens"
REPO_NAME="dev-lab"
CERT_VALIDITY_DAYS=3650  # 10 years
CERT_COMMON_NAME="identity.linkerd.cluster.local"

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

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if gh CLI is installed
    if ! command -v gh &> /dev/null; then
        error "GitHub CLI (gh) is not installed"
        echo "Install it from: https://cli.github.com/"
        exit 1
    fi
    
    # Check if logged in to GitHub
    if ! gh auth status &> /dev/null; then
        error "Not logged in to GitHub CLI"
        echo "Run: gh auth login"
        exit 1
    fi
    
    # Check if openssl is available
    if ! command -v openssl &> /dev/null; then
        error "OpenSSL is not installed"
        exit 1
    fi
    
    success "All prerequisites met"
}

# Generate trust anchor certificate
generate_trust_anchor() {
    log "Generating Linkerd trust anchor certificate..."
    
    # Create temporary directory
    local temp_dir=$(mktemp -d)
    local key_file="$temp_dir/ca.key"
    local cert_file="$temp_dir/ca.crt"
    
    # Generate private key
    openssl genrsa -out "$key_file" 4096
    
    # Generate self-signed certificate
    openssl req -x509 -new -key "$key_file" -sha256 -days $CERT_VALIDITY_DAYS -out "$cert_file" \
        -subj "/CN=$CERT_COMMON_NAME/O=linkerd" \
        -addext "subjectAltName=DNS:$CERT_COMMON_NAME" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "basicConstraints=critical,CA:true"
    
    # Verify certificate
    openssl x509 -in "$cert_file" -text -noout > /dev/null
    
    success "Trust anchor certificate generated successfully"
    
    # Store file paths for later use
    echo "$cert_file" > /tmp/linkerd_cert_path
    echo "$key_file" > /tmp/linkerd_key_path
    echo "$temp_dir" > /tmp/linkerd_temp_dir
}

# Upload certificates to GitHub Secrets
upload_to_github_secrets() {
    log "Uploading certificates to GitHub Secrets..."
    
    local cert_file=$(cat /tmp/linkerd_cert_path)
    local key_file=$(cat /tmp/linkerd_key_path)
    
    # Read certificate and key content
    local cert_content=$(cat "$cert_file")
    local key_content=$(cat "$key_file")
    
    # Upload certificate to GitHub Secrets
    echo "$cert_content" | gh secret set LINKERD_TRUST_ANCHOR_CERT --repo "$REPO_OWNER/$REPO_NAME"
    
    # Upload private key to GitHub Secrets
    echo "$key_content" | gh secret set LINKERD_TRUST_ANCHOR_KEY --repo "$REPO_OWNER/$REPO_NAME"
    
    success "Certificates uploaded to GitHub Secrets successfully"
    
    # Show certificate info
    log "Certificate information:"
    openssl x509 -in "$cert_file" -text -noout | grep -A 2 "Subject:\|Not Before:\|Not After:\|Serial Number:"
}

# Cleanup temporary files
cleanup() {
    if [ -f /tmp/linkerd_temp_dir ]; then
        local temp_dir=$(cat /tmp/linkerd_temp_dir)
        if [ -d "$temp_dir" ]; then
            rm -rf "$temp_dir"
            log "Cleaned up temporary files"
        fi
        rm -f /tmp/linkerd_cert_path /tmp/linkerd_key_path /tmp/linkerd_temp_dir
    fi
}

# Verify GitHub Secrets
verify_secrets() {
    log "Verifying GitHub Secrets..."
    
    # List secrets to verify they exist
    if gh secret list --repo "$REPO_OWNER/$REPO_NAME" | grep -q "LINKERD_TRUST_ANCHOR_CERT"; then
        success "LINKERD_TRUST_ANCHOR_CERT secret exists"
    else
        error "LINKERD_TRUST_ANCHOR_CERT secret not found"
        return 1
    fi
    
    if gh secret list --repo "$REPO_OWNER/$REPO_NAME" | grep -q "LINKERD_TRUST_ANCHOR_KEY"; then
        success "LINKERD_TRUST_ANCHOR_KEY secret exists"
    else
        error "LINKERD_TRUST_ANCHOR_KEY secret not found"
        return 1
    fi
}

# Main function
main() {
    echo "🔐 Linkerd Trust Anchor Certificate Generator for GitHub Secrets"
    echo "================================================================"
    echo ""
    
    case "${1:-generate}" in
        "generate")
            check_prerequisites
            generate_trust_anchor
            upload_to_github_secrets
            verify_secrets
            cleanup
            echo ""
            success "Trust anchor certificates generated and stored in GitHub Secrets!"
            echo ""
            warn "Next steps:"
            echo "1. Note: This cluster now uses cert-manager to auto-generate trust anchors"
            echo "2. The certificates stored here are for backup/reference purposes"
            echo "3. Deploy the cluster - cert-manager will create new trust anchors automatically"
            ;;
        "verify")
            check_prerequisites
            verify_secrets
            ;;
        "help")
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  generate  Generate new trust anchor and upload to GitHub Secrets (default)"
            echo "  verify    Verify that secrets exist in GitHub"
            echo "  help      Show this help"
            ;;
        *)
            error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Cleanup on exit
trap cleanup EXIT

# Run main function
main "$@"