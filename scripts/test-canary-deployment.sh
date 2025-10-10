#!/bin/bash

# Canary Deployment Test Script
# This script triggers canary deployments for testing dashboard functionality

set -e

APPLICATION="${1:-}"
VERSION="${2:-}"

if [ -z "$APPLICATION" ] || [ -z "$VERSION" ]; then
    echo "Usage: $0 <application> <version>"
    echo ""
    echo "Available applications:"
    echo "  mesh-test-app    - Mesh testing application"
    echo "  order-service    - Order management service"
    echo ""
    echo "Examples:"
    echo "  $0 mesh-test-app v8"
    echo "  $0 order-service v2"
    exit 1
fi

case "$APPLICATION" in
    "mesh-test-app")
        NAMESPACE="mesh-test"
        DEPLOYMENT_FILE="apps/mesh-test-app/k8s/base.yaml"
        IMAGE_NAME="mesh-test-app"
        ;;
    "order-service")
        NAMESPACE="order-system" 
        DEPLOYMENT_FILE="apps/order-service/k8s/base.yaml"
        IMAGE_NAME="order-service"
        ;;
    *)
        echo "❌ Unknown application: $APPLICATION"
        exit 1
        ;;
esac

echo "🚀 Triggering canary deployment for $APPLICATION to version $VERSION"
echo "📁 Namespace: $NAMESPACE"
echo "📝 Deployment file: $DEPLOYMENT_FILE"
echo ""

# Check current canary status
echo "📊 Current canary status:"
kubectl get canary "$APPLICATION" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null && echo "" || echo "Not found"

# Backup current deployment file
cp "$DEPLOYMENT_FILE" "$DEPLOYMENT_FILE.backup"
echo "💾 Backed up deployment file to $DEPLOYMENT_FILE.backup"

# Update image tag
sed -i "s|image: localhost:5000/$IMAGE_NAME:.*|image: localhost:5000/$IMAGE_NAME:$VERSION|g" "$DEPLOYMENT_FILE"

# Update APP_VERSION environment variable
sed -i "s|value: \".*\" *# ← Update version to trigger canary|value: \"$VERSION\"  # ← Update version to trigger canary|g" "$DEPLOYMENT_FILE"

echo "🔄 Updated deployment configuration:"
echo "   Image: localhost:5000/$IMAGE_NAME:$VERSION"
echo "   APP_VERSION: $VERSION"

# Build new image if it's a mesh-test-app
if [ "$APPLICATION" = "mesh-test-app" ]; then
    echo ""
    echo "🔨 Building new image for mesh-test-app..."
    cd apps/mesh-test-app
    docker build -t "localhost:5000/$IMAGE_NAME:$VERSION" .
    docker push "localhost:5000/$IMAGE_NAME:$VERSION"
    cd ../..
    echo "✅ Built and pushed localhost:5000/$IMAGE_NAME:$VERSION"
fi

# Build new image if it's an order-service
if [ "$APPLICATION" = "order-service" ]; then
    echo ""
    echo "🔨 Building new image for order-service..."
    cd apps/order-service
    
    # Update version in package.json
    jq ".version = \"$VERSION\"" package.json > package.json.tmp && mv package.json.tmp package.json
    
    docker build -t "localhost:5000/$IMAGE_NAME:$VERSION" .
    docker push "localhost:5000/$IMAGE_NAME:$VERSION"
    cd ../..
    echo "✅ Built and pushed localhost:5000/$IMAGE_NAME:$VERSION"
fi

echo ""
echo "📦 Applying updated deployment..."
kubectl apply -f "$DEPLOYMENT_FILE"

echo ""
echo "⏱️  Monitoring canary deployment progress..."
echo "   You can watch the progress with:"
echo "   kubectl get canary $APPLICATION -n $NAMESPACE -w"
echo ""
echo "📊 Monitor in Grafana:"
echo "   - Multi-App Dashboard: http://localhost:3000/d/multi-app-canary"
echo "   - $APPLICATION Dashboard: http://localhost:3000/d/$NAMESPACE-$APPLICATION-canary"
echo ""

# Watch canary status for 2 minutes
timeout 120 kubectl get canary "$APPLICATION" -n "$NAMESPACE" -w --no-headers | while read line; do
    status=$(echo "$line" | awk '{print $2}')
    weight=$(echo "$line" | awk '{print $3}')
    echo "$(date '+%H:%M:%S') - Status: $status, Weight: $weight%"
    
    # Exit if succeeded or failed
    if [[ "$status" == "Succeeded" ]] || [[ "$status" == "Failed" ]]; then
        echo ""
        if [[ "$status" == "Succeeded" ]]; then
            echo "✅ Canary deployment succeeded!"
        else
            echo "❌ Canary deployment failed!"
        fi
        break
    fi
done || echo "⏰ Timeout reached, canary still progressing..."

echo ""
echo "🔍 Final canary status:"
kubectl get canary "$APPLICATION" -n "$NAMESPACE"

echo ""
echo "🧹 To restore previous version:"
echo "   mv $DEPLOYMENT_FILE.backup $DEPLOYMENT_FILE"
echo "   kubectl apply -f $DEPLOYMENT_FILE"