#!/bin/bash

echo "🎯 Load Balancing Demonstration Script"
echo "======================================"
echo ""

# Get the loadtester pod
LOADTESTER_POD=$(kubectl get pod -n mesh-test -l app=flagger-loadtester -o jsonpath='{.items[0].metadata.name}')
echo "📋 Using loadtester pod: $LOADTESTER_POD"
echo ""

echo "� Step 1: Current Service Setup Analysis"
echo "   → Checking all mesh-test-app services:"
kubectl get services -n mesh-test -l app=mesh-test-app
echo ""

echo "📦 Step 2: Pod Distribution Analysis"
echo "   → Primary pods (mesh-test-app-primary):"
kubectl get pods -n mesh-test -l app=mesh-test-app-primary --no-headers | awk '{print "     ✅ " $1 " - " $3}'
echo "   → Canary pods (mesh-test-app):"
kubectl get pods -n mesh-test -l app=mesh-test-app --no-headers | awk '{print "     🚀 " $1 " - " $3}'
echo ""

echo "🚀 Step 3: Generating load to PRIMARY service..."
echo "   → Testing load balancing across primary pods"

# Generate load to the primary service specifically
echo "   → Starting load to mesh-test-app-primary service..."
for i in {1..5}; do
  kubectl exec -n mesh-test -c loadtester $LOADTESTER_POD -- \
    hey -z 45s -q 3 -c 2 http://mesh-test-app-primary.mesh-test.svc.cluster.local/ > /dev/null 2>&1 &
done

echo "   → Starting load to main service (should route to primary)..."
for i in {1..3}; do
  kubectl exec -n mesh-test -c loadtester $LOADTESTER_POD -- \
    hey -z 45s -q 2 -c 1 http://mesh-test-app.mesh-test.svc.cluster.local/ > /dev/null 2>&1 &
done

echo "   ✅ Background load started (45 seconds)"
echo ""

echo "⏱️  Step 4: Waiting for metrics to populate..."
sleep 20

echo ""
echo "🎯 PRIMARY PODS - Load Distribution:"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app-primary\",direction=\"inbound\"}[1m])) by (pod)" | \
  jq -r '.data.result[]? | "   📦 " + .metric.pod + ": " + (.value[1] | tonumber | . * 100 | round / 100 | tostring) + " req/s"'

echo ""
echo "🚀 CANARY PODS - Load Distribution:"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app\",direction=\"inbound\"}[1m])) by (pod)" | \
  jq -r '.data.result[]? | "   � " + .metric.pod + ": " + (.value[1] | tonumber | . * 100 | round / 100 | tostring) + " req/s"'

echo ""
echo "📈 PRIMARY Load Balancing Evenness Score:"
curl -s "http://localhost:9091/api/v1/query?query=1 - (stddev(sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app-primary\",direction=\"inbound\"}[1m])) by (pod)) / avg(sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app-primary\",direction=\"inbound\"}[1m])) by (pod)))" | \
  jq -r '.data.result[]? | "   🎯 Primary Evenness: " + (.value[1] | tonumber | . * 100 | round | tostring) + "% (closer to 100% = better load balancing)"'

echo ""
echo "🔗 Step 5: Service Endpoint Verification..."
echo "   → Primary service endpoints:"
kubectl get endpoints mesh-test-app-primary -n mesh-test -o json | \
  jq -r '.subsets[]?.addresses[]? | "     ✅ " + .targetRef.name + " @ " + .ip'

echo "   → Main service endpoints (Flagger controlled):"
kubectl get endpoints mesh-test-app -n mesh-test -o json | \
  jq -r '.subsets[]?.addresses[]? | "     🎛️  " + .targetRef.name + " @ " + .ip'

echo ""
echo "⏱️  Step 6: Extended monitoring (30 more seconds)..."
sleep 30

echo ""
echo "🎯 UPDATED Load Distribution:"
echo "   → Primary pods:"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app-primary\",direction=\"inbound\"}[1m])) by (pod)" | \
  jq -r '.data.result[]? | "     📦 " + .metric.pod + ": " + (.value[1] | tonumber | . * 100 | round / 100 | tostring) + " req/s"'

echo "   → Canary pods:"
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app\",direction=\"inbound\"}[1m])) by (pod)" | \
  jq -r '.data.result[]? | "     � " + .metric.pod + ": " + (.value[1] | tonumber | . * 100 | round / 100 | tostring) + " req/s"'

echo ""
echo "� Step 7: Linkerd Load Balancing Algorithm Check..."
echo "   → Checking balancer endpoint counts:"
curl -s "http://localhost:9091/api/v1/query?query=linkerd_proxy_balancer_endpoints{namespace=\"mesh-test\"}" | \
  jq -r '.data.result[]? | "     🔗 " + .metric.pod + " (" + .metric.deployment + ") sees " + .value[1] + " endpoints"'

echo ""
echo "🧹 Cleanup: Stop background load generation"
jobs -p | xargs -r kill 2>/dev/null
echo "   ✅ Background load stopped"

echo ""
echo "🎛️  Dashboard Access:"
echo "   → Open Grafana: http://localhost:3000"
echo "   → Dashboard: 'Linkerd Canary Deployment Dashboard'"
echo "   → New Load Balancing Panels:"
echo "     • Load Balancing Distribution by Pod (pie chart)"
echo "     • Request Rate per Pod (time series)"
echo "     • Pod Response Times Distribution" 
echo "     • Load Balance Evenness Score"
echo ""

echo "📊 To monitor real-time load balancing:"
echo "   → Run: ./monitor-load-balancing.sh"
echo ""

echo "🎯 What to Look For:"
echo "   ✅ PRIMARY pods should show roughly equal request rates"
echo "   ✅ Evenness score should be >80% for good load balancing"
echo "   ✅ All primary pods should be registered as service endpoints"
echo "   ✅ Canary pods may have 0 traffic (normal when no canary active)"