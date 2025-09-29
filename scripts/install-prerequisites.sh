#!/bin/bash

# Dev Lab Prerequisites Installation Script
# Installs required tools for dev-lab environment

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
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

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Detect OS and package manager
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command_exists apt-get; then
            echo "debian"
        elif command_exists dnf; then
            echo "fedora"
        elif command_exists yum; then
            echo "redhat"
        elif command_exists pacman; then
            echo "arch"
        else
            echo "unknown-linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    else
        echo "unknown"
    fi
}

# Install Docker
install_docker() {
    local os_type="$1"
    
    log "Installing Docker..."
    
    case "$os_type" in
        "debian")
            # Ubuntu/Debian Docker installation
            sudo apt-get update
            sudo apt-get install -y ca-certificates curl gnupg lsb-release
            
            # Add Docker's official GPG key
            sudo mkdir -p /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            
            # Add Docker repository
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
            
            # Install Docker
            sudo apt-get update
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            
            # Start Docker and add user to group
            sudo systemctl enable docker
            sudo systemctl start docker
            sudo usermod -aG docker "$USER"
            ;;
        "fedora")
            sudo dnf install -y dnf-plugins-core
            sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
            sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
            sudo systemctl enable docker
            sudo systemctl start docker
            sudo usermod -aG docker "$USER"
            ;;
        "macos")
            if command_exists brew; then
                brew install --cask docker
            else
                warn "Please install Docker Desktop from https://docs.docker.com/desktop/mac/install/"
                return 1
            fi
            ;;
        *)
            warn "Please install Docker manually for your OS"
            return 1
            ;;
    esac
    
    success "Docker installed"
}

# Install kubectl
install_kubectl() {
    log "Installing kubectl..."
    
    # Get latest stable version
    local kubectl_version
    kubectl_version=$(curl -L -s https://dl.k8s.io/release/stable.txt)
    
    case "$(uname -s)" in
        "Linux")
            curl -LO "https://dl.k8s.io/release/${kubectl_version}/bin/linux/amd64/kubectl"
            ;;
        "Darwin")
            curl -LO "https://dl.k8s.io/release/${kubectl_version}/bin/darwin/amd64/kubectl"
            ;;
        *)
            error "Unsupported OS for kubectl installation"
            return 1
            ;;
    esac
    
    chmod +x kubectl
    sudo mv kubectl /usr/local/bin/kubectl
    
    success "kubectl installed"
}

# Install Helm
install_helm() {
    log "Installing Helm..."
    
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    
    success "Helm installed"
}

# Install KinD
install_kind() {
    log "Installing KinD..."
    
    case "$(uname -s)" in
        "Linux")
            curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64"
            ;;
        "Darwin")
            curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.20.0/kind-darwin-amd64"
            ;;
        *)
            error "Unsupported OS for KinD installation"
            return 1
            ;;
    esac
    
    chmod +x ./kind
    sudo mv ./kind /usr/local/bin/kind
    
    success "KinD installed"
}

# Install jq
install_jq() {
    local os_type="$1"
    
    log "Installing jq..."
    
    case "$os_type" in
        "debian")
            sudo apt-get update && sudo apt-get install -y jq
            ;;
        "fedora")
            sudo dnf install -y jq
            ;;
        "redhat")
            sudo yum install -y epel-release && sudo yum install -y jq
            ;;
        "arch")
            sudo pacman -S jq
            ;;
        "macos")
            if command_exists brew; then
                brew install jq
            else
                curl -Lo jq https://github.com/stedolan/jq/releases/latest/download/jq-osx-amd64
                chmod +x jq
                sudo mv jq /usr/local/bin/jq
            fi
            ;;
        *)
            # Fallback to static binary
            curl -Lo jq https://github.com/stedolan/jq/releases/latest/download/jq-linux64
            chmod +x jq
            sudo mv jq /usr/local/bin/jq
            ;;
    esac
    
    success "jq installed"
}

# Main installation function
main() {
    echo "🔧 Dev Lab Prerequisites Installation"
    echo ""
    
    local os_type
    os_type=$(detect_os)
    log "Detected OS: $os_type"
    echo ""
    
    # Check what's already installed
    local to_install=()
    
    for tool in docker kubectl helm kind jq; do
        if command_exists "$tool"; then
            success "$tool is already installed"
        else
            to_install+=("$tool")
        fi
    done
    
    if [[ ${#to_install[@]} -eq 0 ]]; then
        success "All prerequisites are already installed!"
        echo ""
        echo "Next steps:"
        echo "  ./scripts/bootstrap.sh    # Bootstrap the environment"
        exit 0
    fi
    
    echo ""
    log "Installing missing tools: ${to_install[*]}"
    echo ""
    
    # Install each missing tool
    for tool in "${to_install[@]}"; do
        case "$tool" in
            "docker")
                install_docker "$os_type"
                ;;
            "kubectl")
                install_kubectl
                ;;
            "helm")
                install_helm
                ;;
            "kind")
                install_kind
                ;;
            "jq")
                install_jq "$os_type"
                ;;
        esac
    done
    
    echo ""
    success "🎉 All prerequisites installed successfully!"
    echo ""
    
    if [[ " ${to_install[*]} " =~ " docker " ]]; then
        warn "Docker was installed. You may need to:"
        echo "  1. Log out and back in (to apply group membership)"
        echo "  2. Or run: newgrp docker"
        echo ""
    fi
    
    echo "Next steps:"
    echo "  ./scripts/bootstrap.sh              # Bootstrap the environment"
    echo "  ./scripts/deploy-traditional.sh     # Traditional deployment"
    echo "  ./scripts/deploy-gitops.sh          # GitOps deployment"
    echo ""
}

main "$@"