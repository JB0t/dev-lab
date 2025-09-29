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
APP_DIR="$(dirname "$SCRIPT_DIR")"

COMMAND=${1:-help}

# Build v2 of the application with visible changes
build_v2() {
    log "Building version 2 of the application..."
    
    cd "$APP_DIR"
    
    # Create a modified server.js for v2 that shows clear differences
    cp server.js server.js.backup
    
    # Modify the app to clearly show it's v2
    sed -i 's/Service Mesh Test Application/Service Mesh Test Application v2 - CANARY/g' server.js
    sed -i 's/Item 1/Item 1 (v2)/g' server.js
    sed -i 's/Item 2/Item 2 (v2)/g' server.js
    sed -i 's/Item 3/Item 3 (v2)/g' server.js
    
    # Build v2 image
    docker build -t mesh-test-app:v2 .
    
    # Load into KinD
    kind load docker-image mesh-test-app:v2 --name dev-lab
    
    # Restore original server.js
    mv server.js.backup server.js
    
    success "Version 2 image built and loaded"
}

# Deploy canary (v2) alongside stable (v1)
deploy_canary() {
    log "Deploying canary version..."
    
    # First, update the existing deployment to use v1 service
    kubectl patch service mesh-test-app-service -n mesh-test -p '{"metadata":{"name":"mesh-test-app-service-v1"}}'
    kubectl label deployment mesh-test-app -n mesh-test version=v1 --overwrite
    
    # Deploy v2 and traffic split
    kubectl apply -f "$APP_DIR/k8s/canary.yaml"
    
    log "Waiting for canary deployment to be ready..."
    kubectl wait --for=condition=available deployment/mesh-test-app-v2 -n mesh-test --timeout=300s
    
    success "Canary deployment ready"
}

# Monitor traffic distribution
monitor_traffic() {
    log "Monitoring traffic distribution..."
    
    echo "Current traffic split:"
    kubectl get trafficsplit -n mesh-test -o yaml | grep -A 10 "backends:"
    
    echo ""
    echo "Pod status:"
    kubectl get pods -n mesh-test -l app=mesh-test-app
    
    echo ""
    echo "Service endpoints:"
    kubectl get endpoints -n mesh-test
}

# Test traffic distribution
test_traffic() {
    local requests=${1:-20}
    log "Testing traffic distribution with $requests requests..."
    
    # Start port-forward in background
    kubectl port-forward -n mesh-test svc/mesh-test-app-service 8080:80 &
    PF_PID=$!
    
    sleep 3
    
    echo "Making $requests requests to see traffic distribution:"
    for i in $(seq 1 $requests); do
        version=$(curl -s http://localhost:8080/ | jq -r '.version' 2>/dev/null || echo "unknown")
        message=$(curl -s http://localhost:8080/ | jq -r '.message' 2>/dev/null || echo "unknown")
        echo "Request $i: Version=$version, Message=$message"
        sleep 0.5
    done
    
    # Clean up port-forward
    kill $PF_PID
    
    success "Traffic test completed"
}

# Promote canary to stable (100% traffic)
promote_canary() {
    log "Promoting canary to stable (100% traffic)..."
    
    # Update traffic split to send 100% to v2
    kubectl patch trafficsplit mesh-test-app-split -n mesh-test --type='merge' -p='{
        "spec": {
            "backends": [
                {"service": "mesh-test-app-service-v1", "weight": 0},
                {"service": "mesh-test-app-service-v2", "weight": 100}
            ]
        }
    }'
    
    success "Canary promoted to receive 100% traffic"
    
    log "Waiting 30 seconds to verify stability..."
    sleep 30
    
    log "Scaling down v1 deployment..."
    kubectl scale deployment mesh-test-app -n mesh-test --replicas=0
    
    log "Scaling up v2 deployment..."
    kubectl scale deployment mesh-test-app-v2 -n mesh-test --replicas=3
    
    success "Canary promotion completed"
}

# Rollback canary deployment
rollback_canary() {
    log "Rolling back canary deployment..."
    
    # Set traffic split to 100% v1
    kubectl patch trafficsplit mesh-test-app-split -n mesh-test --type='merge' -p='{
        "spec": {
            "backends": [
                {"service": "mesh-test-app-service-v1", "weight": 100},
                {"service": "mesh-test-app-service-v2", "weight": 0}
            ]
        }
    }'
    
    log "Waiting 10 seconds for traffic to stabilize..."
    sleep 10
    
    log "Removing canary deployment..."
    kubectl delete deployment mesh-test-app-v2 -n mesh-test
    kubectl delete service mesh-test-app-service-v2 -n mesh-test
    kubectl delete trafficsplit mesh-test-app-split -n mesh-test
    
    success "Canary rollback completed"
}

# Update traffic weights
update_weights() {
    local v1_weight=${1:-80}
    local v2_weight=${2:-20}
    
    log "Updating traffic weights: v1=$v1_weight%, v2=$v2_weight%"
    
    kubectl patch trafficsplit mesh-test-app-split -n mesh-test --type='merge' -p='{
        "spec": {
            "backends": [
                {"service": "mesh-test-app-service-v1", "weight": '$v1_weight'},
                {"service": "mesh-test-app-service-v2", "weight": '$v2_weight'}
            ]
        }
    }'
    
    success "Traffic weights updated"
}

# Show help
show_help() {
    echo "Canary Deployment Management Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  build-v2                 Build version 2 of the application"
    echo "  deploy                   Deploy canary version alongside stable"
    echo "  monitor                  Show current traffic distribution"
    echo "  test [requests]          Test traffic distribution (default: 20 requests)"
    echo "  promote                  Promote canary to stable (100% traffic)"
    echo "  rollback                 Rollback canary deployment"
    echo "  weights <v1%> <v2%>      Update traffic weights"
    echo "  status                   Show deployment status"
    echo "  cleanup                  Clean up all canary resources"
    echo ""
    echo "Examples:"
    echo "  $0 build-v2              # Build v2 image"
    echo "  $0 deploy                # Deploy canary with 10% traffic"
    echo "  $0 test 50               # Test with 50 requests"
    echo "  $0 weights 70 30         # Set 70% v1, 30% v2"
    echo "  $0 promote               # Promote canary to stable"
    echo "  $0 rollback              # Rollback to stable"
}

# Show status
show_status() {
    echo "=== Canary Deployment Status ==="
    echo ""
    echo "📊 Traffic Split:"
    kubectl get trafficsplit -n mesh-test 2>/dev/null || echo "No traffic split configured"
    echo ""
    echo "🚀 Deployments:"
    kubectl get deployments -n mesh-test -l app=mesh-test-app
    echo ""
    echo "🎯 Pods:"
    kubectl get pods -n mesh-test -l app=mesh-test-app
    echo ""
    echo "🔗 Services:"
    kubectl get services -n mesh-test -l app=mesh-test-app
}

# Cleanup all canary resources
cleanup() {
    log "Cleaning up canary resources..."
    
    kubectl delete trafficsplit mesh-test-app-split -n mesh-test 2>/dev/null || true
    kubectl delete deployment mesh-test-app-v2 -n mesh-test 2>/dev/null || true
    kubectl delete service mesh-test-app-service-v2 -n mesh-test 2>/dev/null || true
    
    success "Cleanup completed"
}

# Handle cleanup on script exit
trap_cleanup() {
    if [[ -n "${PF_PID:-}" ]]; then
        kill $PF_PID 2>/dev/null || true
    fi
}

trap trap_cleanup EXIT

# Main execution
case $COMMAND in
    build-v2)
        build_v2
        ;;
    deploy)
        build_v2
        deploy_canary
        monitor_traffic
        ;;
    monitor)
        monitor_traffic
        ;;
    test)
        test_traffic "$2"
        ;;
    promote)
        promote_canary
        ;;
    rollback)
        rollback_canary
        ;;
    weights)
        update_weights "$2" "$3"
        ;;
    status)
        show_status
        ;;
    cleanup)
        cleanup
        ;;
    help|*)
        show_help
        ;;
esac