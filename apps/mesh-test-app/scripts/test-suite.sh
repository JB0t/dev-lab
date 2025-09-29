#!/bin/bash

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
PURPLE='\033[0;35m'
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

info() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${PURPLE}ℹ $1${NC}"
}

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

# Test configuration
NAMESPACE="mesh-test"
SERVICE="mesh-test-app-service"
PORT="8080"
DURATION=${1:-60}
REQUESTS_PER_SECOND=${2:-10}
PARALLEL_WORKERS=${3:-5}

# Test results
RESULTS_DIR="$APP_DIR/test-results"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TEST_LOG="$RESULTS_DIR/test-$TIMESTAMP.log"

# Create results directory
mkdir -p "$RESULTS_DIR"

# Cleanup function
cleanup() {
    if [[ -n "${PF_PID:-}" ]]; then
        kill $PF_PID 2>/dev/null || true
    fi
    
    # Kill any background jobs
    jobs -p | xargs -r kill 2>/dev/null || true
}

trap cleanup EXIT

# Start port-forward
start_port_forward() {
    log "Starting port-forward to service..."
    kubectl port-forward -n "$NAMESPACE" svc/"$SERVICE" "$PORT":80 &
    PF_PID=$!
    
    # Wait for port-forward to be ready
    for i in {1..10}; do
        if curl -s http://localhost:$PORT/health >/dev/null 2>&1; then
            success "Port-forward ready"
            return 0
        fi
        sleep 1
    done
    
    error "Port-forward failed to start"
    return 1
}

# Generate load using curl
generate_load() {
    local duration=$1
    local rps=$2
    local worker_id=$3
    local endpoint=${4:-"/"}
    
    local requests=0
    local successes=0
    local errors=0
    local total_time=0
    
    local end_time=$((SECONDS + duration))
    
    while [[ $SECONDS -lt $end_time ]]; do
        local start_req=$(date +%s.%N)
        
        if response=$(curl -s -w "%{http_code},%{time_total}" http://localhost:$PORT$endpoint 2>/dev/null); then
            local http_code=$(echo "$response" | tail -1 | cut -d',' -f1)
            local req_time=$(echo "$response" | tail -1 | cut -d',' -f2)
            
            requests=$((requests + 1))
            total_time=$(echo "$total_time + $req_time" | bc -l)
            
            if [[ $http_code -eq 200 ]]; then
                successes=$((successes + 1))
            else
                errors=$((errors + 1))
                echo "Worker $worker_id: Error $http_code at $(date)" >> "$TEST_LOG"
            fi
        else
            errors=$((errors + 1))
            echo "Worker $worker_id: Connection error at $(date)" >> "$TEST_LOG"
        fi
        
        # Rate limiting
        sleep $(echo "scale=3; 1.0 / $rps" | bc -l)
    done
    
    local avg_time=$(echo "scale=3; $total_time / $requests" | bc -l)
    echo "Worker $worker_id: $requests requests, $successes success, $errors errors, avg: ${avg_time}s" >> "$TEST_LOG"
}

# Monitor service metrics during test
monitor_metrics() {
    local duration=$1
    local end_time=$((SECONDS + duration))
    
    while [[ $SECONDS -lt $end_time ]]; do
        {
            echo "=== Metrics at $(date) ==="
            
            # Pod status
            echo "Pods:"
            kubectl get pods -n "$NAMESPACE" -l app=mesh-test-app
            
            # Service mesh stats
            if command -v linkerd &> /dev/null; then
                echo -e "\nLinkerd Stats:"
                linkerd viz stat -n "$NAMESPACE" 2>/dev/null || echo "Linkerd stats unavailable"
            fi
            
            # Application metrics
            echo -e "\nApplication Metrics:"
            curl -s http://localhost:$PORT/metrics | grep -E "(http_requests_total|http_request_duration)" | head -10
            
            echo "=========================="
        } >> "$TEST_LOG"
        
        sleep 10
    done
}

# Test zero-downtime deployment
test_zero_downtime() {
    log "Starting zero-downtime deployment test..."
    
    # Start continuous monitoring
    monitor_metrics $DURATION &
    MONITOR_PID=$!
    
    # Start load generation
    log "Starting load generation with $PARALLEL_WORKERS workers at $REQUESTS_PER_SECOND RPS for ${DURATION}s..."
    
    for i in $(seq 1 $PARALLEL_WORKERS); do
        generate_load $DURATION $REQUESTS_PER_SECOND $i &
    done
    
    # Wait a bit then trigger deployment
    sleep 10
    
    log "Triggering canary deployment..."
    "$SCRIPT_DIR/canary-deploy.sh" deploy &
    
    # Wait for load generation to complete
    wait
    
    # Stop monitoring
    kill $MONITOR_PID 2>/dev/null || true
    
    success "Zero-downtime test completed"
}

# Test service mesh mTLS
test_mtls() {
    log "Testing service mesh mTLS..."
    
    if ! command -v linkerd &> /dev/null; then
        warn "Linkerd not available, skipping mTLS test"
        return
    fi
    
    # Check mTLS status
    echo "=== mTLS Status ===" >> "$TEST_LOG"
    linkerd viz edges -n "$NAMESPACE" >> "$TEST_LOG" 2>&1 || echo "mTLS check failed" >> "$TEST_LOG"
    
    # Test encrypted traffic
    log "Checking for encrypted traffic..."
    timeout 10 linkerd viz tap -n "$NAMESPACE" --to svc/redis-service | head -20 >> "$TEST_LOG" 2>&1 || true
    
    success "mTLS test completed"
}

# Test application health during deployment
test_health_during_deployment() {
    log "Testing application health during deployment..."
    
    local health_errors=0
    local health_checks=0
    
    # Start health monitoring
    {
        local end_time=$((SECONDS + DURATION))
        while [[ $SECONDS -lt $end_time ]]; do
            health_checks=$((health_checks + 1))
            
            if ! curl -s http://localhost:$PORT/health/ready >/dev/null; then
                health_errors=$((health_errors + 1))
                echo "Health check failed at $(date)" >> "$TEST_LOG"
            fi
            
            sleep 2
        done
        
        echo "Health check summary: $health_errors errors out of $health_checks checks" >> "$TEST_LOG"
    } &
    
    HEALTH_PID=$!
    
    # Trigger rolling update
    sleep 5
    log "Triggering rolling update..."
    kubectl patch deployment mesh-test-app -n "$NAMESPACE" -p '{"spec":{"template":{"metadata":{"annotations":{"test/restart":"'$(date +%s)'"}}}}}'
    
    # Wait for health monitoring to complete
    wait $HEALTH_PID
    
    success "Health monitoring during deployment completed"
}

# Analyze test results
analyze_results() {
    log "Analyzing test results..."
    
    echo "=== Test Analysis ===" >> "$TEST_LOG"
    echo "Test completed at: $(date)" >> "$TEST_LOG"
    
    # Count errors
    local total_errors=$(grep -c "Error\|error\|failed" "$TEST_LOG" 2>/dev/null || echo "0")
    local health_failures=$(grep -c "Health check failed" "$TEST_LOG" 2>/dev/null || echo "0")
    
    echo "Total errors detected: $total_errors" >> "$TEST_LOG"
    echo "Health check failures: $health_failures" >> "$TEST_LOG"
    
    # Calculate success rate
    local worker_stats=$(grep "Worker.*requests" "$TEST_LOG")
    if [[ -n "$worker_stats" ]]; then
        local total_requests=$(echo "$worker_stats" | awk '{sum += $3} END {print sum}')
        local total_successes=$(echo "$worker_stats" | awk '{sum += $5} END {print sum}')
        local success_rate=$(echo "scale=2; $total_successes * 100 / $total_requests" | bc -l)
        
        echo "Total requests: $total_requests" >> "$TEST_LOG"
        echo "Successful requests: $total_successes" >> "$TEST_LOG"
        echo "Success rate: $success_rate%" >> "$TEST_LOG"
    fi
    
    echo "=== End Analysis ===" >> "$TEST_LOG"
    
    # Display results
    echo ""
    success "=== Test Results ==="
    echo ""
    info "Test log: $TEST_LOG"
    echo ""
    
    if [[ $total_errors -eq 0 && $health_failures -eq 0 ]]; then
        success "✅ ZERO-DOWNTIME DEPLOYMENT SUCCESSFUL!"
        success "   No errors or health check failures detected"
    else
        error "❌ DEPLOYMENT HAD ISSUES:"
        error "   Total errors: $total_errors"
        error "   Health failures: $health_failures"
    fi
    
    echo ""
    info "Full results in: $TEST_LOG"
    
    # Show summary
    echo ""
    echo "Last 20 lines of test log:"
    tail -20 "$TEST_LOG"
}

# Run comprehensive test suite
run_test_suite() {
    log "Starting comprehensive service mesh and zero-downtime deployment test..."
    log "Duration: ${DURATION}s, RPS: $REQUESTS_PER_SECOND, Workers: $PARALLEL_WORKERS"
    
    echo "=== Test Started at $(date) ===" > "$TEST_LOG"
    echo "Configuration: Duration=${DURATION}s, RPS=$REQUESTS_PER_SECOND, Workers=$PARALLEL_WORKERS" >> "$TEST_LOG"
    
    # Start port-forward
    start_port_forward
    
    # Test components
    test_mtls
    test_zero_downtime
    test_health_during_deployment
    
    # Analyze results
    analyze_results
    
    success "Test suite completed!"
}

# Show help
show_help() {
    echo "Service Mesh and Zero-Downtime Deployment Test Suite"
    echo ""
    echo "Usage: $0 [duration] [requests_per_second] [parallel_workers]"
    echo ""
    echo "Parameters:"
    echo "  duration            Test duration in seconds (default: 60)"
    echo "  requests_per_second Requests per second per worker (default: 10)"
    echo "  parallel_workers    Number of parallel load generators (default: 5)"
    echo ""
    echo "Examples:"
    echo "  $0                  # Run with defaults (60s, 10 RPS, 5 workers)"
    echo "  $0 120              # Run for 2 minutes"
    echo "  $0 120 20           # Run for 2 minutes at 20 RPS"
    echo "  $0 120 20 10        # Run for 2 minutes at 20 RPS with 10 workers"
    echo ""
    echo "The test will:"
    echo "  1. Generate continuous load to the application"
    echo "  2. Trigger a canary deployment during the load test"
    echo "  3. Monitor application health and service mesh metrics"
    echo "  4. Verify zero-downtime deployment success"
    echo "  5. Test mTLS functionality"
    echo ""
    echo "Results will be saved to: $RESULTS_DIR/"
}

# Main execution
if [[ "${1:-}" == "help" || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    show_help
else
    run_test_suite
fi