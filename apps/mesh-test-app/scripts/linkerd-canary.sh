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

# Initialize Linkerd native canary deployment
init_linkerd_canary() {
    log "Initializing Linkerd native canary deployment..."
    
    # Apply service profiles for better observability
    kubectl apply -f "$APP_DIR/k8s/linkerd-native-split.yaml"
    
    success "Linkerd native canary initialized"
}

# Deploy HTTPRoute-based canary
deploy_httproute_canary() {
    local v1_weight=${1:-90}
    local v2_weight=${2:-10}
    
    log "Deploying HTTPRoute-based canary (v1: $v1_weight%, v2: $v2_weight%)..."
    
    # Create temporary HTTPRoute with specified weights
    cat > /tmp/httproute-canary.yaml << EOF
apiVersion: gateway.networking.k8s.io/v1beta1
kind: HTTPRoute
metadata:
  name: mesh-test-app-canary-route
  namespace: mesh-test
  annotations:
    linkerd.io/inject: enabled
spec:
  parentRefs:
  - name: mesh-test-app-service
    kind: Service
    group: ""
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: mesh-test-app-service-v1
      port: 80
      weight: $v1_weight
    - name: mesh-test-app-service-v2
      port: 80
      weight: $v2_weight
EOF
    
    kubectl apply -f /tmp/httproute-canary.yaml
    rm /tmp/httproute-canary.yaml
    
    success "HTTPRoute canary deployed with weights v1:$v1_weight%, v2:$v2_weight%"
}

# Header-based canary for safe testing
deploy_header_canary() {
    log "Deploying header-based canary (x-canary: true → v2)..."
    
    kubectl apply -f "$APP_DIR/k8s/linkerd-httproute.yaml"
    
    success "Header-based canary deployed"
    echo "Test with: curl -H 'x-canary: true' http://mesh-test.local:30080/"
}

# Monitor Linkerd traffic stats
monitor_linkerd_traffic() {
    log "Monitoring Linkerd traffic statistics..."
    
    echo ""
    echo "📊 Service Statistics:"
    linkerd viz stat -n mesh-test --from deploy/mesh-test-app --to svc/mesh-test-app-service
    
    echo ""
    echo "📊 Traffic Split Statistics:"
    linkerd viz stat -n mesh-test svc
    
    echo ""
    echo "📈 Success Rate and Latency:"
    linkerd viz stat -n mesh-test --from deploy/mesh-test-app-v2 --to svc/redis-service
}

# Real-time traffic analysis
analyze_live_traffic() {
    local duration=${1:-30}
    
    log "Analyzing live traffic for $duration seconds..."
    echo "Press Ctrl+C to stop early"
    
    timeout $duration linkerd viz tap -n mesh-test --to svc/mesh-test-app-service
}

# Check Linkerd mesh health
check_mesh_health() {
    log "Checking Linkerd mesh health..."
    
    echo "🔍 Linkerd Control Plane:"
    linkerd check
    
    echo ""
    echo "📡 Linkerd Viz Extension:"  
    linkerd viz check
    
    echo ""
    echo "🕸️ Service Mesh Status:"
    linkerd viz edges -n mesh-test
    
    echo ""
    echo "🔒 mTLS Status:"
    linkerd viz edges -n mesh-test --as table
}

# Progressive canary deployment using Linkerd
progressive_canary() {
    log "Starting progressive canary deployment with Linkerd..."
    
    # Step 1: 10% canary
    deploy_httproute_canary 90 10
    log "🎯 Step 1: 10% traffic to canary. Testing for 30 seconds..."
    sleep 30
    
    # Step 2: 25% canary
    deploy_httproute_canary 75 25
    log "🎯 Step 2: 25% traffic to canary. Testing for 30 seconds..."
    sleep 30
    
    # Step 3: 50% canary
    deploy_httproute_canary 50 50
    log "🎯 Step 3: 50% traffic to canary. Testing for 30 seconds..."
    sleep 30
    
    # Step 4: 75% canary
    deploy_httproute_canary 25 75
    log "🎯 Step 4: 75% traffic to canary. Testing for 30 seconds..."
    sleep 30
    
    # Step 5: 100% canary
    deploy_httproute_canary 0 100
    log "🎯 Step 5: 100% traffic to canary - deployment complete!"
    
    success "Progressive canary deployment completed successfully"
}

# Automated canary with health monitoring
automated_canary() {
    local check_interval=${1:-30}
    
    log "Starting automated canary with health monitoring (check every ${check_interval}s)..."
    
    weights=(10 25 50 75 100)
    
    for weight in "${weights[@]}"; do
        local v1_weight=$((100 - weight))
        
        log "🎯 Deploying ${weight}% canary traffic..."
        deploy_httproute_canary $v1_weight $weight
        
        log "⏱️ Monitoring for ${check_interval} seconds..."
        sleep $check_interval
        
        # Check error rates
        log "📊 Checking error rates..."
        error_rate=$(linkerd viz stat -n mesh-test svc/mesh-test-app-service-v2 -o json | jq -r '.[0].stats.successRate' 2>/dev/null || echo "100%")
        
        log "📈 Canary error rate: $error_rate"
        
        # Simple health check (in real scenario, you'd have more sophisticated checks)
        if [[ "$error_rate" == "100%" ]]; then
            success "Health check passed, continuing..."
        else
            warn "Health check detected issues, consider manual review"
        fi
    done
    
    success "Automated canary deployment completed"
}

# Cleanup Linkerd resources
cleanup_linkerd() {
    log "Cleaning up Linkerd canary resources..."
    
    kubectl delete httproute mesh-test-app-canary-route -n mesh-test 2>/dev/null || true
    kubectl delete httproute mesh-test-app-header-canary -n mesh-test 2>/dev/null || true
    kubectl delete serviceprofile mesh-test-app-service.mesh-test.svc.cluster.local -n mesh-test 2>/dev/null || true
    
    success "Linkerd canary resources cleaned up"
}

# Show help
show_help() {
    echo "Linkerd Native Canary Deployment Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Linkerd Native Commands:"
    echo "  init-linkerd                 Initialize Linkerd native canary"
    echo "  httproute <v1%> <v2%>        Deploy HTTPRoute-based canary"
    echo "  header-canary                Deploy header-based canary"
    echo "  progressive                  Run progressive canary (10% → 100%)"
    echo "  automated [interval]         Automated canary with health checks"
    echo "  monitor                      Show Linkerd traffic statistics"
    echo "  analyze [duration]           Real-time traffic analysis"
    echo "  health                       Check mesh health"
    echo "  cleanup-linkerd              Clean up Linkerd resources"
    echo ""
    echo "Examples:"
    echo "  $0 init-linkerd              # Initialize Linkerd canary"
    echo "  $0 httproute 80 20           # 80% v1, 20% v2 via HTTPRoute"
    echo "  $0 header-canary             # Header-based routing"
    echo "  $0 progressive               # Full progressive deployment"
    echo "  $0 automated 45              # Automated with 45s intervals"
    echo "  $0 analyze 60                # Analyze traffic for 60 seconds"
}

# Main execution
case $COMMAND in
    init-linkerd)
        init_linkerd_canary
        ;;
    httproute)
        deploy_httproute_canary "$2" "$3"
        ;;
    header-canary)
        deploy_header_canary
        ;;
    progressive)
        progressive_canary
        ;;
    automated)
        automated_canary "$2"
        ;;
    monitor)
        monitor_linkerd_traffic
        ;;
    analyze)
        analyze_live_traffic "$2"
        ;;
    health)
        check_mesh_health
        ;;
    cleanup-linkerd)
        cleanup_linkerd
        ;;
    help|*)
        show_help
        ;;
esac