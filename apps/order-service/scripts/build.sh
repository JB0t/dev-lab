#!/bin/bash

# Order Service Build and Deploy Script
set -e

REGISTRY="localhost:5000"
IMAGE_NAME="order-service"
VERSION="v1"

echo "Building Order Service container image..."

# Build the image
docker build -t ${REGISTRY}/${IMAGE_NAME}:${VERSION} .

echo "Pushing image to local registry..."

# Push to local registry
docker push ${REGISTRY}/${IMAGE_NAME}:${VERSION}

echo "✓ Order Service image built and pushed: ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
echo ""
echo "To deploy:"
echo "  kubectl apply -k k8s/"
echo ""
echo "To trigger a canary deployment:"
echo "  1. Update the image tag in k8s/base.yaml"
echo "  2. Update the APP_VERSION environment variable"
echo "  3. Apply the changes: kubectl apply -k k8s/"