#!/bin/bash
# scripts/validate-canary-service.sh
# Validate that a canary-enabled service meets all requirements

set -e

SERVICE_NAME="$1"

if [ -z "$SERVICE_NAME" ]; then
    echo "Usage: $0 <service-name>"
    echo "Example: $0 user-service"
    exit 1
fi

SERVICE_DIR="apps/$SERVICE_NAME"

echo "🔍 Validating canary service: $SERVICE_NAME"
echo "========================================"

# Check directory structure
echo "📁 Checking directory structure..."
if [ ! -d "$SERVICE_DIR" ]; then
    echo "❌ Service directory $SERVICE_DIR does not exist"
    exit 1
fi

required_files=(
    "$SERVICE_DIR/k8s/base.yaml"
    "$SERVICE_DIR/k8s/canary.yaml"
    "$SERVICE_DIR/k8s/loadtester.yaml"
    "$SERVICE_DIR/k8s/metrics.yaml"
    "$SERVICE_DIR/k8s/kustomization.yaml"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "✅ $file exists"
    else
        echo "❌ $file missing"
        exit 1
    fi
done

# Check namespace injection annotation
echo ""
echo "🔗 Checking Linkerd injection..."
if grep -q "linkerd.io/inject: enabled" "$SERVICE_DIR/k8s/base.yaml"; then
    echo "✅ Linkerd injection enabled"
else
    echo "❌ Linkerd injection not found"
    exit 1
fi

# Check health endpoints
echo ""
echo "🏥 Checking health endpoints..."
if grep -q "/health/live" "$SERVICE_DIR/k8s/base.yaml" && grep -q "/health/ready" "$SERVICE_DIR/k8s/base.yaml"; then
    echo "✅ Health endpoints configured"
else
    echo "❌ Health endpoints missing"
    exit 1
fi

# Check canary configuration
echo ""
echo "🐤 Checking canary configuration..."
if grep -q "kind: Canary" "$SERVICE_DIR/k8s/canary.yaml"; then
    echo "✅ Canary resource exists"
else
    echo "❌ Canary resource missing"
    exit 1
fi

# Check metric templates
echo ""
echo "📊 Checking metric templates..."
if grep -q "linkerd-success-rate" "$SERVICE_DIR/k8s/metrics.yaml" && grep -q "linkerd-request-duration" "$SERVICE_DIR/k8s/metrics.yaml"; then
    echo "✅ Metric templates configured"
else
    echo "❌ Metric templates missing"
    exit 1
fi

# Check if deployed to cluster
echo ""
echo "🚢 Checking cluster deployment..."
if kubectl get namespace "$SERVICE_NAME" > /dev/null 2>&1; then
    echo "✅ Namespace exists in cluster"
    
    # Check deployment
    if kubectl get deployment "$SERVICE_NAME" -n "$SERVICE_NAME" > /dev/null 2>&1; then
        echo "✅ Deployment exists"
        
        # Check pods
        ready_pods=$(kubectl get pods -n "$SERVICE_NAME" -l app="$SERVICE_NAME" --field-selector=status.phase=Running -o jsonpath='{.items[*].status.containerStatuses[*].ready}' | grep -o true | wc -l)
        total_containers=$(kubectl get pods -n "$SERVICE_NAME" -l app="$SERVICE_NAME" --field-selector=status.phase=Running -o jsonpath='{.items[*].status.containerStatuses[*].ready}' | wc -w)
        
        if [ "$ready_pods" -eq "$total_containers" ] && [ "$total_containers" -gt 0 ]; then
            echo "✅ All pods ready ($ready_pods/$total_containers)"
        else
            echo "⚠️  Some pods not ready ($ready_pods/$total_containers)"
        fi
    else
        echo "⚠️  Deployment not found in cluster"
    fi
    
    # Check canary
    if kubectl get canary "$SERVICE_NAME" -n "$SERVICE_NAME" > /dev/null 2>&1; then
        echo "✅ Canary resource exists"
        status=$(kubectl get canary "$SERVICE_NAME" -n "$SERVICE_NAME" -o jsonpath='{.status.phase}')
        echo "   Status: $status"
    else
        echo "⚠️  Canary resource not found in cluster"
    fi
    
    # Check loadtester
    if kubectl get deployment flagger-loadtester -n "$SERVICE_NAME" > /dev/null 2>&1; then
        echo "✅ Loadtester deployed"
    else
        echo "⚠️  Loadtester not found"
    fi
    
else
    echo "⚠️  Service not deployed to cluster"
fi

echo ""
echo "🔧 Quick validation commands:"
echo "   kubectl get canary $SERVICE_NAME -n $SERVICE_NAME"
echo "   kubectl describe canary $SERVICE_NAME -n $SERVICE_NAME"
echo "   kubectl get pods -n $SERVICE_NAME"
echo "   kubectl logs -n $SERVICE_NAME -l app=$SERVICE_NAME"
echo ""
echo "🌐 Test endpoints:"
echo "   kubectl port-forward -n $SERVICE_NAME svc/$SERVICE_NAME 8080:80"
echo "   curl http://localhost:8080/health/live"
echo "   curl http://localhost:8080/health/ready"
echo "   curl http://localhost:8080/"