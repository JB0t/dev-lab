#!/bin/bash

echo "=== mTLS Demonstration Test ==="
echo ""

echo "🔍 Testing mTLS status using existing loadtester pod"
LOADTESTER_POD=$(kubectl get pod -n mesh-test -l app=flagger-loadtester -o jsonpath='{.items[0].metadata.name}')
echo "   Using pod: $LOADTESTER_POD"
echo ""

echo "📊 1. Testing connection to PLAIN HTTP service (no mTLS):"
echo "   → Calling test-app-plain-svc.mtls-test-plain.svc.cluster.local:9898"
kubectl exec -n mesh-test -c loadtester $LOADTESTER_POD -- curl -s --max-time 5 http://test-app-plain-svc.mtls-test-plain.svc.cluster.local:9898/version | head -3
echo ""

echo "🔒 2. Testing connection to SECURE service (with mTLS):"
echo "   → Calling test-app-secure-svc.mtls-test-secure.svc.cluster.local:9898"
kubectl exec -n mesh-test -c loadtester $LOADTESTER_POD -- curl -s --max-time 5 http://test-app-secure-svc.mtls-test-secure.svc.cluster.local:9898/version | head -3
echo ""

echo "📈 3. Checking Prometheus metrics for mTLS status:"
echo ""

# Generate some traffic first
echo "   → Generating test traffic..."
for i in {1..3}; do
  kubectl exec -n mesh-test -c loadtester $LOADTESTER_POD -- curl -s http://test-app-plain-svc.mtls-test-plain.svc.cluster.local:9898/headers > /dev/null 2>&1 &
  kubectl exec -n mesh-test -c loadtester $LOADTESTER_POD -- curl -s http://test-app-secure-svc.mtls-test-secure.svc.cluster.local:9898/headers > /dev/null 2>&1 &
done
wait

sleep 15

echo "   → Plain HTTP traffic (should show tls=no_identity):"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mtls-test-plain\"}[1m]))by(tls)" | jq -r '.data.result[]? | "   TLS Status: " + .metric.tls + " - Rate: " + .value[1] + " req/s"'

echo ""
echo "   → mTLS traffic (should show tls=true):"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mtls-test-secure\",direction=\"inbound\"}[1m]))by(tls)" | jq -r '.data.result[]? | "   TLS Status: " + .metric.tls + " - Rate: " + .value[1] + " req/s"'

echo ""
echo "🎯 4. Summary:"
echo "   - Plain namespace: NO Linkerd injection = NO mTLS"
echo "   - Secure namespace: WITH Linkerd injection = mTLS enabled"
echo "   - Check your Grafana dashboard for real-time mTLS metrics!"
echo ""
echo "🔧 5. Cleanup when done:"
echo "   kubectl delete namespace mtls-test-plain mtls-test-secure"

echo ""
echo "🎯 4. Summary:"
echo "   - Plain namespace: NO Linkerd injection = NO mTLS"
echo "   - Secure namespace: WITH Linkerd injection = mTLS enabled"
echo "   - Check your Grafana dashboard for real-time mTLS metrics!"
echo ""
echo "🔧 5. Cleanup when done:"
echo "   kubectl delete namespace mtls-test-plain mtls-test-secure"