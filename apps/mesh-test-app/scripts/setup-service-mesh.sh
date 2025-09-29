#!/bin/bash

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${BLUE}$1${NC}"
}

success() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${GREEN}✓ $1${NC}"
}

error() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${RED}✗ $1${NC}"
}

warn() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${YELLOW}⚠ $1${NC}"
}

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "=== Setting up Service Mesh Testing Environment ==="

# Check if Linkerd CLI is installed
check_linkerd_cli() {
    log "Checking for Linkerd CLI..."
    if ! command -v linkerd &> /dev/null; then
        log "Installing Linkerd CLI..."
        curl -sL https://run.linkerd.io/install | sh
        export PATH=$PATH:$HOME/.linkerd2/bin
        
        if ! command -v linkerd &> /dev/null; then
            error "Failed to install Linkerd CLI"
            exit 1
        fi
    fi
    success "Linkerd CLI is available"
}

# Install Gateway API CRDs (required for Linkerd)
install_gateway_api() {
    log "Installing Gateway API CRDs (required for Linkerd)..."
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
    
    log "Waiting for Gateway API CRDs to be ready..."
    kubectl wait --for condition=established --timeout=60s crd/gateways.gateway.networking.k8s.io
    kubectl wait --for condition=established --timeout=60s crd/httproutes.gateway.networking.k8s.io
    
    success "Gateway API CRDs installed successfully"
}

# Install Linkerd
install_linkerd() {
    log "Checking Linkerd pre-flight..."
    linkerd check --pre
    
    log "Installing Linkerd CRDs..."
    linkerd install --crds | kubectl apply -f -
    
    log "Installing Linkerd control plane..."
    linkerd install | kubectl apply -f -
    
    log "Waiting for Linkerd to be ready..."
    linkerd check
    
    success "Linkerd installed successfully"
}

# Install Linkerd Viz extension for observability
install_linkerd_viz() {
    log "Installing Linkerd Viz extension..."
    linkerd viz install | kubectl apply -f -
    
    log "Waiting for Linkerd Viz to be ready..."
    linkerd viz check
    
    success "Linkerd Viz installed successfully"
}

# Install TrafficSplit CRDs manually (since linkerd smi command may not exist)
install_trafficsplit_crd() {
    log "Installing TrafficSplit CRD for canary deployments..."
    
    if ! kubectl get crd trafficsplits.split.smi-spec.io &> /dev/null; then
        kubectl apply -f k8s/trafficsplit-crd.yaml
        
        log "Waiting for TrafficSplit CRD to be ready..."
        kubectl wait --for condition=established --timeout=60s crd/trafficsplits.split.smi-spec.io
        
        success "TrafficSplit CRD installed successfully"
    else 
        success "TrafficSplit CRD already exists"
    fi
}

# Build and deploy the test application
deploy_app() {
    log "Setting server-level file monitoring limits..."
    sudo sysctl -w fs.inotify.max_user_watches=2099999999
    sudo sysctl -w fs.inotify.max_user_instances=2099999999
    sudo sysctl -w fs.inotify.max_queued_events=2099999999

    log "Building mesh test application..."
    cd "$SCRIPT_DIR/../"
    
    # Build the Docker images
    docker build -t mesh-test-app:v1 .
    
    # Create a simple v2 by tagging v1 (for initial setup)
    docker tag mesh-test-app:v1 mesh-test-app:v2
    
    # Load into KinD cluster
    kind load docker-image mesh-test-app:v1 --name dev-lab
    kind load docker-image mesh-test-app:v2 --name dev-lab
    
    success "Application images built and loaded"
    
    log "Deploying basic application and database..."
    kubectl apply -f k8s/base.yaml
    kubectl apply -f k8s/redis.yaml
    
    log "Waiting for basic deployments to be ready..."
    kubectl wait --for=condition=available deployment/redis -n mesh-test --timeout=300s
    kubectl wait --for=condition=available deployment/mesh-test-app -n mesh-test --timeout=300s
    
    success "Basic application deployed successfully"
    
    log "Deploying canary setup..."
    
    # Try TrafficSplit-based canary first, fall back to simple canary
    if kubectl get crd trafficsplits.split.smi-spec.io &> /dev/null; then
        log "Using TrafficSplit for canary deployment..."
        kubectl apply -f k8s/canary.yaml || {
            warn "TrafficSplit failed, using simple canary approach..."
            kubectl apply -f k8s/canary-simple.yaml
        }
    else
        log "Using simple canary deployment (no TrafficSplit)..."
        kubectl apply -f k8s/canary-simple.yaml
    fi
    
    log "Waiting for canary deployment to be ready..."
    kubectl wait --for=condition=available deployment/mesh-test-app-v2 -n mesh-test --timeout=300s
    
    success "Canary deployment setup completed"
}

# Test the setup
test_setup() {
    log "Testing the deployed application..."
    
    # Get service details
    kubectl get pods -n mesh-test
    kubectl get services -n mesh-test
    
    # Test port-forward and API
    log "Testing API endpoints..."
    kubectl port-forward -n mesh-test svc/mesh-test-app-service 8080:80 &
    PF_PID=$!
    
    sleep 5
    
    # Test endpoints
    echo "Testing health endpoint:"
    curl -s http://localhost:8080/health | jq '.' || echo "jq not available"
    
    echo -e "\nTesting main endpoint:"
    curl -s http://localhost:8080/ | jq '.' || echo "jq not available"
    
    echo -e "\nTesting data endpoint:"
    curl -s http://localhost:8080/api/data | jq '.' || echo "jq not available"
    
    # Kill port-forward
    kill $PF_PID
    
    success "Application is responding correctly"
}

# Show access information
show_access_info() {
    echo ""
    success "=== Service Mesh Test Environment Ready ==="
    echo ""
    echo "🔗 Linkerd Dashboard:"
    echo "   kubectl port-forward -n linkerd-viz svc/web 8084:8084"
    echo "   http://localhost:8084"
    echo ""
    echo "📱 Test Application (Browser Access):"
    echo "   http://mesh-test.local:30080"
    echo "   http://localhost:30080"
    echo ""
    echo "📱 Test Application (Port Forward):"
    echo "   kubectl port-forward -n mesh-test svc/mesh-test-app-service 8080:80"
    echo "   http://localhost:8080"
    echo ""
    echo "📊 Application Metrics:"
    echo "   http://mesh-test.local:30080/metrics"
    echo ""
    echo "🏥 Health Checks:"
    echo "   http://mesh-test.local:30080/health"
    echo "   http://mesh-test.local:30080/health/live"
    echo "   http://mesh-test.local:30080/health/ready"
    echo ""
    echo "🔍 Linkerd Commands:"
    echo "   linkerd viz stat -n mesh-test"
    echo "   linkerd viz top -n mesh-test"
    echo "   linkerd viz tap -n mesh-test"
    echo ""
    echo "🐛 Debugging:"
    echo "   kubectl get pods -n mesh-test"
    echo "   kubectl logs -n mesh-test -l app=mesh-test-app"
    echo "   kubectl describe pod -n mesh-test <pod-name>"
}

# Main execution
main() {
    check_linkerd_cli
    
    if ! linkerd check &> /dev/null; then
        install_gateway_api
        install_linkerd
        install_linkerd_viz
    else
        success "Linkerd already installed"
    fi
    
    # Install TrafficSplit CRD for canary deployments
    install_trafficsplit_crd
    
    deploy_app
    test_setup
    show_access_info
}

# Handle cleanup on script exit
cleanup() {
    if [[ -n "${PF_PID:-}" ]]; then
        kill $PF_PID 2>/dev/null || true
    fi
}

trap cleanup EXIT

# Run main function
main "$@"