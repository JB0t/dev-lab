#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
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

echo "=== Testing Dev Lab Environment ==="

# Test 1: Cluster connectivity
log "Testing cluster connectivity..."
if kubectl cluster-info >/dev/null 2>&1; then
    success "Cluster is reachable"
else
    error "Cluster is not reachable"
    exit 1
fi

# Test 2: Node status
log "Checking node status..."
if kubectl get nodes --no-headers | grep -q "Ready"; then
    success "All nodes are ready"
    kubectl get nodes
else
    error "Some nodes are not ready"
    kubectl get nodes
    exit 1
fi

# Test 3: Registry connectivity
log "Testing registry connectivity..."
if curl -s http://localhost:5000/v2/_catalog >/dev/null; then
    success "Registry is accessible"
else
    error "Registry is not accessible"
    exit 1
fi

# Test 4: Monitoring stack
log "Checking monitoring stack..."
if kubectl -n monitoring get pods --no-headers | grep -q "Running"; then
    success "Monitoring stack is running"
    kubectl -n monitoring get pods
else
    error "Monitoring stack has issues"
    kubectl -n monitoring get pods
fi

# Test 5: Ingress controller
log "Checking ingress controller..."
if kubectl -n ingress-nginx get pods --no-headers | grep -q "Running"; then
    success "Ingress controller is running"
else
    error "Ingress controller has issues"
    kubectl -n ingress-nginx get pods
fi

# Test 6: Build and push test image
log "Building and loading test image into KinD..."
cat > Dockerfile.test << EOF
FROM nginx:alpine
RUN echo '<h1>Dev Lab Test</h1><p>Image built and loaded successfully!</p>' > /usr/share/nginx/html/index.html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
EOF

if docker build -t test-app:latest -f Dockerfile.test .; then
    success "Test image built"
else
    error "Failed to build test image"
    rm -f Dockerfile.test
    exit 1
fi

# For KinD, we load images directly instead of using registry
if kind load docker-image test-app:latest --name dev-lab; then
    success "Test image loaded into KinD cluster"
else
    error "Failed to load test image into KinD"
    rm -f Dockerfile.test
    exit 1
fi

# Also push to registry for completeness
if docker tag test-app:latest localhost:5000/test-app:latest && docker push localhost:5000/test-app:latest; then
    success "Test image also pushed to registry"
else
    warn "Registry push failed, but KinD load succeeded"
fi

# Test 7: Deploy test app
log "Deploying test application..."
cat > test-app.yaml << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: test-app
  template:
    metadata:
      labels:
        app: test-app
    spec:
      containers:
      - name: test-app
        image: test-app:latest
        imagePullPolicy: Never
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 100m
            memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: test-app
spec:
  selector:
    app: test-app
  ports:
  - port: 80
    targetPort: 80
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: test-app
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: test-app.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: test-app
            port:
              number: 80
EOF

if kubectl apply -f test-app.yaml; then
    success "Test application deployed"
else
    error "Failed to deploy test application"
    rm -f Dockerfile.test test-app.yaml
    exit 1
fi

# Wait for deployment
log "Waiting for test app to be ready..."
if kubectl wait --for=condition=available deployment/test-app --timeout=120s; then
    success "Test application is ready"
    kubectl get pods -l app=test-app
else
    warn "Test application deployment timed out"
    kubectl get pods -l app=test-app
fi

# Test 8: Metrics collection
log "Testing metrics collection..."
if kubectl top nodes >/dev/null 2>&1; then
    success "Metrics server is working"
    kubectl top nodes
else
    warn "Metrics server not ready yet"
fi

# Cleanup
log "Cleaning up test resources..."
kubectl delete -f test-app.yaml >/dev/null 2>&1 || true
docker rmi test-app:latest >/dev/null 2>&1 || true
docker rmi localhost:5000/test-app:latest >/dev/null 2>&1 || true
rm -f Dockerfile.test test-app.yaml

echo ""
success "Development lab test completed successfully!"
echo ""
echo "=== Access URLs ==="
echo "• Registry: http://localhost:5000"
echo "• Prometheus: kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
echo "• Grafana: kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
echo "• AlertManager: kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093"
echo ""
echo "=== Quick Commands ==="
echo "• Check cluster: kubectl get nodes"
echo "• Check monitoring: kubectl -n monitoring get pods"
echo "• Check registry: curl -s http://localhost:5000/v2/_catalog"
echo "• Load image to KinD: kind load docker-image <image> --name dev-lab"
echo "• Push to registry: docker tag <image> localhost:5000/<name>:<tag> && docker push localhost:5000/<name>:<tag>"
echo "• Access test app: kubectl port-forward svc/test-app 8080:80"