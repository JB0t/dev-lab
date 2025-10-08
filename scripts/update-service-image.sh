#!/bin/bash
# scripts/update-service-image.sh
# Update service image version and trigger canary deployment

set -e

SERVICE_NAME="$1"
NEW_VERSION="${2:-v2}"

if [ -z "$SERVICE_NAME" ]; then
    echo "Usage: $0 <service-name> [new-version]"
    echo "Example: $0 user-service v2"
    exit 1
fi

SERVICE_DIR="apps/$SERVICE_NAME"

if [ ! -d "$SERVICE_DIR" ]; then
    echo "❌ Service directory $SERVICE_DIR does not exist"
    exit 1
fi

echo "🚀 Updating $SERVICE_NAME to version $NEW_VERSION"

# Update deployment image
echo "📝 Updating deployment image..."
sed -i "s|localhost:5000/$SERVICE_NAME:.*|localhost:5000/$SERVICE_NAME:$NEW_VERSION|g" "$SERVICE_DIR/k8s/base.yaml"

# Update package.json version if it exists
if [ -f "$SERVICE_DIR/package.json" ]; then
    echo "📦 Updating package.json version..."
    sed -i "s|\"version\": \".*\"|\"version\": \"$NEW_VERSION\"|g" "$SERVICE_DIR/package.json"
fi

echo "🔨 Building and pushing new image..."
cd "$SERVICE_DIR"
docker build -t "localhost:5000/$SERVICE_NAME:$NEW_VERSION" .
docker push "localhost:5000/$SERVICE_NAME:$NEW_VERSION"

echo "🚢 Applying updated manifests..."
cd - > /dev/null
kubectl apply -k "$SERVICE_DIR/k8s/"

echo "✅ Update complete! Monitor canary progress:"
echo "   kubectl get canary $SERVICE_NAME -n $SERVICE_NAME -w"
echo "   kubectl describe canary $SERVICE_NAME -n $SERVICE_NAME"
echo ""
echo "📊 Monitor in Grafana:"
echo "   Multi-app dashboard: http://localhost:3001"
echo "   Individual dashboard: Search for '$SERVICE_NAME Canary'"