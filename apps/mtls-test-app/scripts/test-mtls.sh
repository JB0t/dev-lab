#!/bin/bash

echo "=== mTLS Demonstration Test ==="
echo ""

echo "🔍 Testing mTLS status using ephemeral curl pods"
echo "   Creating temporary test pods as needed..."
echo ""

# Function to run curl commands in ephemeral pods
run_curl_test() {
    local namespace=$1
    local url=$2
    local description=$3
    
    echo "   → $description"
    echo "   → Calling $url"
    
    # Create ephemeral pod with Linkerd injection matching the namespace
    local inject_annotation=""
    if kubectl get namespace "$namespace" -o jsonpath='{.metadata.annotations.linkerd\.io/inject}' 2>/dev/null | grep -q "enabled"; then
        inject_annotation="linkerd.io/inject: enabled"
    fi
    
    kubectl run curl-test-$(date +%s) \
        --namespace="$namespace" \
        --image=curlimages/curl:latest \
        --rm -i --restart=Never \
        --annotations="$inject_annotation" \
        --command -- curl -s --max-time 10 "$url" 2>/dev/null | head -3
}

echo "📊 1. Testing connection to PLAIN HTTP service (no mTLS):"
run_curl_test "mtls-test-plain" "http://test-app-plain-svc.mtls-test-plain.svc.cluster.local:9898/version" "Plain HTTP connection (no Linkerd sidecar)"
echo ""

echo "🔒 2. Testing connection to SECURE service (with mTLS):"
run_curl_test "mtls-test-secure" "http://test-app-secure-svc.mtls-test-secure.svc.cluster.local:9898/version" "mTLS connection (with Linkerd sidecar)"
echo ""

echo "📈 3. Checking Prometheus metrics for mTLS status:"
echo ""

# Check if Prometheus is available
if ! curl -s "http://localhost:9091/api/v1/query?query=up" > /dev/null 2>&1; then
    echo "   ⚠️  Prometheus not available at localhost:9091"
    echo "   💡 Run: kubectl port-forward -n linkerd-viz svc/prometheus 9091:9090"
    echo "   📊 Skipping metrics check..."
    echo ""
else

# Generate some traffic first
echo "   → Generating test traffic..."
for i in {1..3}; do
  kubectl run traffic-plain-$(date +%s)-$i \
    --namespace="mtls-test-plain" \
    --image=curlimages/curl:latest \
    --rm --restart=Never \
    --command -- curl -s http://test-app-plain-svc.mtls-test-plain.svc.cluster.local:9898/headers > /dev/null 2>&1 &
  
  kubectl run traffic-secure-$(date +%s)-$i \
    --namespace="mtls-test-secure" \
    --image=curlimages/curl:latest \
    --rm --restart=Never \
    --annotations="linkerd.io/inject: enabled" \
    --command -- curl -s http://test-app-secure-svc.mtls-test-secure.svc.cluster.local:9898/headers > /dev/null 2>&1 &
done
wait

sleep 15

echo "   → Plain HTTP traffic (should show tls=no_identity):"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mtls-test-plain\"}[1m]))by(tls)" | jq -r '.data.result[]? | "   TLS Status: " + .metric.tls + " - Rate: " + .value[1] + " req/s"'

echo ""
echo "   → mTLS traffic (should show tls=true):"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mtls-test-secure\",direction=\"inbound\"}[1m]))by(tls)" | jq -r '.data.result[]? | "   TLS Status: " + .metric.tls + " - Rate: " + .value[1] + " req/s"'
fi

echo ""
echo "🎯 4. Summary:"
echo "   - Plain namespace: NO Linkerd injection = NO mTLS"
echo "   - Secure namespace: WITH Linkerd injection = mTLS enabled"
echo "   - Check your Grafana dashboard for real-time mTLS metrics!"
echo ""
echo "🔧 5. Cleanup when done:"
echo "   kubectl delete namespace mtls-test-plain mtls-test-secure"