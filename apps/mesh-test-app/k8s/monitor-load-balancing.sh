#!/bin/bash

echo "🔄 Real-time Load Balancing Monitor"
echo "=================================="
echo "Press Ctrl+C to stop monitoring"
echo ""

while true; do
  clear
  echo "🕐 $(date)"
  echo "=================================="
  echo ""
  
  echo "📊 Current Load Distribution:"
  curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app-primary\",direction=\"inbound\"}[1m])) by (pod)" | \
    jq -r '.data.result[]? | "   📦 " + .metric.pod + ": " + (.value[1] | tonumber | . * 100 | round / 100 | tostring) + " req/s"'
  
  echo ""
  echo "🎯 Load Balancing Evenness:"
  curl -s "http://localhost:9091/api/v1/query?query=1 - (stddev(sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app-primary\",direction=\"inbound\"}[1m])) by (pod)) / avg(sum(rate(response_total{namespace=\"mesh-test\",deployment=\"mesh-test-app-primary\",direction=\"inbound\"}[1m])) by (pod)))" | \
    jq -r '.data.result[]? | "   Score: " + (.value[1] | tonumber | . * 100 | round | tostring) + "% (100% = perfect balance)"'
  
  echo ""
  echo "🔗 Service Endpoints:"
  kubectl get endpoints mesh-test-app-service -n mesh-test -o json | \
    jq -r '.subsets[]?.addresses[]? | "   ✅ " + .targetRef.name + " @ " + .ip'
  
  echo ""
  echo "⏱️  Refreshing in 5 seconds..."
  sleep 5
done