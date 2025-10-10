#!/bin/bash
# scripts/create-canary-service.sh
# Generate a new canary-enabled service with all required components

set -e

SERVICE_NAME="$1"
PORT="${2:-3000}"
MONITORING_LEVEL="${3:-basic}"

if [ -z "$SERVICE_NAME" ]; then
    echo "Usage: $0 <service-name> [port] [monitoring-level]"
    echo "Example: $0 user-service 8080 enhanced"
    echo ""
    echo "Monitoring levels:"
    echo "  basic    - Standard metrics (faster deployment)"
    echo "  enhanced - Advanced metrics with PodMonitor (production recommended)"
    exit 1
fi

echo "🚀 Creating canary-enabled service: $SERVICE_NAME (port: $PORT, monitoring: $MONITORING_LEVEL)"

# Create service directory structure
SERVICE_DIR="apps/$SERVICE_NAME"
mkdir -p "$SERVICE_DIR/k8s"

echo "📝 Generating Kubernetes manifests..."

# Generate base.yaml
cat > "$SERVICE_DIR/k8s/base.yaml" << EOF
---
apiVersion: v1
kind: Namespace
metadata:
  name: $SERVICE_NAME
  labels:
    name: $SERVICE_NAME
  annotations:
    linkerd.io/inject: enabled

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $SERVICE_NAME
  namespace: $SERVICE_NAME
  labels:
    app: $SERVICE_NAME
    version: v1
spec:
  replicas: 3
  revisionHistoryLimit: 1
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
    type: RollingUpdate
  selector:
    matchLabels:
      app: $SERVICE_NAME
      version: v1
  template:
    metadata:
      labels:
        app: $SERVICE_NAME
        version: v1
    spec:
      containers:
      - name: $SERVICE_NAME
        image: localhost:5000/$SERVICE_NAME:v1
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: $PORT
          name: http
        env:
        - name: APP_VERSION
          value: "v1"
        - name: NODE_ENV
          value: "production"
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 150m
            memory: 128Mi
        livenessProbe:
          httpGet:
            path: /health/live
            port: $PORT
          initialDelaySeconds: 30
          periodSeconds: 10
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health/ready
            port: $PORT
          initialDelaySeconds: 5
          periodSeconds: 5
          failureThreshold: 3
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 10"]

---
apiVersion: v1
kind: Service
metadata:
  name: $SERVICE_NAME
  namespace: $SERVICE_NAME
  labels:
    app: $SERVICE_NAME
spec:
  selector:
    app: $SERVICE_NAME
  ports:
  - port: 80
    targetPort: $PORT
    name: http
  type: ClusterIP

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: $SERVICE_NAME-ingress
  namespace: $SERVICE_NAME
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: $SERVICE_NAME.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: $SERVICE_NAME
            port:
              number: 80
EOF

# Generate canary.yaml
cat > "$SERVICE_DIR/k8s/canary.yaml" << EOF
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: $SERVICE_NAME
  namespace: $SERVICE_NAME
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: $SERVICE_NAME
  
  service:
    port: 80
    targetPort: $PORT
    portDiscovery: true
  
  analysis:
    interval: 45s
    threshold: 3
    maxWeight: 30
    stepWeight: 5
    primaryReadyThreshold: 1
    canaryReadyThreshold: 1
    
    metrics:
    - name: success-rate
      templateRef:
        name: linkerd-success-rate
        namespace: $SERVICE_NAME
      thresholdRange:
        min: 97
      interval: 1m
    
    - name: latency
      templateRef:
        name: linkerd-request-duration
        namespace: $SERVICE_NAME
      thresholdRange:
        max: 300
      interval: 1m
    
    webhooks:
    # Basic health check
    - name: $SERVICE_NAME-health-check
      url: http://flagger-loadtester.$SERVICE_NAME/
      timeout: 15s
      type: pre-rollout
      metadata:
        type: bash
        cmd: |
          curl -sf http://$SERVICE_NAME-canary.$SERVICE_NAME/health/live > /dev/null &&
          curl -sf http://$SERVICE_NAME-canary.$SERVICE_NAME/health/ready > /dev/null
    
    # Load testing
    - name: $SERVICE_NAME-load-test
      url: http://flagger-loadtester.$SERVICE_NAME/
      timeout: 30s
      metadata:
        type: cmd
        cmd: "hey -z 25s -q 8 -c 2 -H 'User-Agent: Flagger-$SERVICE_NAME' http://$SERVICE_NAME-canary.$SERVICE_NAME/"
    
    # Basic functional test
    - name: $SERVICE_NAME-functional-test
      url: http://flagger-loadtester.$SERVICE_NAME/
      timeout: 20s
      type: pre-rollout
      metadata:
        type: bash
        cmd: |
          # Basic endpoint test
          response=\$(curl -sf http://$SERVICE_NAME-canary.$SERVICE_NAME/)
          echo "\$response" | grep -q "$SERVICE_NAME"
EOF

# Generate loadtester.yaml
cat > "$SERVICE_DIR/k8s/loadtester.yaml" << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagger-loadtester
  namespace: $SERVICE_NAME
  labels:
    app: flagger-loadtester
spec:
  selector:
    matchLabels:
      app: flagger-loadtester
  template:
    metadata:
      labels:
        app: flagger-loadtester
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
    spec:
      containers:
      - name: loadtester
        image: ghcr.io/fluxcd/flagger-loadtester:0.22.0
        ports:
        - name: http
          containerPort: 8080
        command:
        - ./loadtester
        - -port=8080
        - -log-level=info
        - -timeout=1h
        livenessProbe:
          exec:
            command:
            - wget
            - --quiet
            - --tries=1
            - --timeout=4
            - --spider
            - http://localhost:8080/healthz
          timeoutSeconds: 5
        readinessProbe:
          exec:
            command:
            - wget
            - --quiet
            - --tries=1
            - --timeout=4
            - --spider
            - http://localhost:8080/healthz
          timeoutSeconds: 5
        resources:
          limits:
            memory: "512Mi"
            cpu: "1000m"
          requests:
            memory: "64Mi"
            cpu: "10m"

---
apiVersion: v1
kind: Service
metadata:
  name: flagger-loadtester
  namespace: $SERVICE_NAME
  labels:
    app: flagger-loadtester
spec:
  type: ClusterIP
  selector:
    app: flagger-loadtester
  ports:
  - name: http
    port: 80
    protocol: TCP
    targetPort: http
EOF

# Generate metrics.yaml
cat > "$SERVICE_DIR/k8s/metrics.yaml" << EOF
---
# Basic Linkerd Success Rate Metric Template
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: linkerd-success-rate
  namespace: $SERVICE_NAME
spec:
  provider:
    type: prometheus
    address: http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090
  query: |
    sum(
      rate(
        response_total{
          namespace="{{ namespace }}",
          direction="inbound",
          target_port="$PORT",
          classification!="failure"
        }[{{ interval }}]
      )
    ) 
    / 
    sum(
      rate(
        response_total{
          namespace="{{ namespace }}",
          direction="inbound",
          target_port="$PORT"
        }[{{ interval }}]
      )
    ) * 100

---
# Basic Linkerd Request Duration Metric Template
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: linkerd-request-duration
  namespace: $SERVICE_NAME
spec:
  provider:
    type: prometheus
    address: http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090
  query: |
    histogram_quantile(0.99,
      sum(
        rate(
          response_latency_ms_bucket{
            namespace="{{ namespace }}",
            direction="inbound",
            target_port="$PORT"
          }[{{ interval }}]
        )
      ) by (le)
    )
EOF

# Add enhanced monitoring if requested
if [ "$MONITORING_LEVEL" = "enhanced" ]; then
    cat >> "$SERVICE_DIR/k8s/metrics.yaml" << EOF

---
# Advanced Traffic-based Success Rate (for canary vs primary comparison)
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: linkerd-traffic-success-rate
  namespace: $SERVICE_NAME
spec:
  provider:
    type: prometheus
    address: http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090
  query: |
    sum(
      rate(
        response_total{
          classification!="failure",
          direction="inbound",
          dst_service_name=~"{{name}}-canary|{{name}}-primary",
          dst_service_namespace="{{namespace}}"
        }[{{interval}}]
      )
    ) by (dst_service_name)
    / 
    sum(
      rate(
        response_total{
          direction="inbound",
          dst_service_name=~"{{name}}-canary|{{name}}-primary",
          dst_service_namespace="{{namespace}}"
        }[{{interval}}]
      )
    ) by (dst_service_name) * 100
EOF

    # Generate PodMonitor for enhanced monitoring
    cat > "$SERVICE_DIR/k8s/podmonitor.yaml" << EOF
---
# Application-specific PodMonitor for Enhanced Canary Metrics
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: $SERVICE_NAME-linkerd-proxy
  namespace: $SERVICE_NAME
  labels:
    app: $SERVICE_NAME
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: $SERVICE_NAME
  podMetricsEndpoints:
  - port: linkerd-admin
    interval: 30s
    path: /metrics
    relabelings:
    # Only scrape linkerd-proxy containers
    - sourceLabels: [__meta_kubernetes_pod_container_name]
      action: keep
      regex: linkerd-proxy
    # Add useful labels
    - sourceLabels: [__meta_kubernetes_namespace]
      targetLabel: namespace
    - sourceLabels: [__meta_kubernetes_pod_name]
      targetLabel: pod
    - sourceLabels: [__meta_kubernetes_pod_label_app]
      targetLabel: app
    - sourceLabels: [__meta_kubernetes_pod_label_version]
      targetLabel: version
EOF
fi

# Create basic application template (Node.js example)
cat > "$SERVICE_DIR/package.json" << EOF
{
  "name": "$SERVICE_NAME",
  "version": "v1",
  "main": "server.js",
  "dependencies": {
    "express": "^4.18.0"
  }
}
EOF

cat > "$SERVICE_DIR/server.js" << EOF
const express = require('express');
const app = express();
const port = process.env.PORT || $PORT;
const version = process.env.APP_VERSION || 'v1';

app.use(express.json());

// Request logging middleware
app.use((req, res, next) => {
  console.log(\`\${new Date().toISOString()} - \${req.method} \${req.path} - \${req.ip}\`);
  next();
});

// Health endpoints (REQUIRED)
app.get('/health/live', (req, res) => {
  res.status(200).json({
    status: 'alive',
    service: '$SERVICE_NAME',
    version: version,
    timestamp: new Date().toISOString()
  });
});

app.get('/health/ready', (req, res) => {
  res.status(200).json({
    status: 'ready',
    service: '$SERVICE_NAME',
    version: version,
    timestamp: new Date().toISOString()
  });
});

// Main endpoint
app.get('/', (req, res) => {
  res.json({
    service: '$SERVICE_NAME',
    version: version,
    message: '$SERVICE_NAME is running!',
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
    node_env: process.env.NODE_ENV || 'development'
  });
});

// Metrics endpoint (basic)
app.get('/metrics', (req, res) => {
  const metrics = \`# HELP \${SERVICE_NAME}_uptime_seconds Service uptime in seconds
# TYPE \${SERVICE_NAME}_uptime_seconds gauge
\${SERVICE_NAME}_uptime_seconds{service="\${SERVICE_NAME}",version="\${version}"} \${process.uptime()}
\`;
  res.set('Content-Type', 'text/plain');
  res.send(metrics);
});

// Graceful shutdown (REQUIRED)
process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down gracefully');
  process.exit(0);
});

app.listen(port, () => {
  console.log(\`$SERVICE_NAME \${version} running on port \${port}\`);
  console.log(\`Environment: \${process.env.NODE_ENV || 'development'}\`);
});
EOF

cat > "$SERVICE_DIR/Dockerfile" << EOF
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --only=production
COPY server.js ./
RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001
USER nodejs
EXPOSE $PORT
CMD ["node", "server.js"]
EOF

# Create kustomization.yaml
KUSTOMIZATION_RESOURCES="  - base.yaml
  - canary.yaml
  - loadtester.yaml
  - metrics.yaml"

if [ "$MONITORING_LEVEL" = "enhanced" ]; then
    KUSTOMIZATION_RESOURCES="$KUSTOMIZATION_RESOURCES
  - podmonitor.yaml"
fi

cat > "$SERVICE_DIR/k8s/kustomization.yaml" << EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: $SERVICE_NAME

resources:
$KUSTOMIZATION_RESOURCES

commonLabels:
  app.kubernetes.io/name: $SERVICE_NAME
  app.kubernetes.io/part-of: dev-lab
  app.kubernetes.io/component: canary-service
EOF

echo "✅ Service $SERVICE_NAME created successfully with $MONITORING_LEVEL monitoring!"
echo ""
echo "📋 Next steps:"
echo "   1. Review and customize the generated files in $SERVICE_DIR/"
echo "   2. Build and push the Docker image:"
echo "      cd $SERVICE_DIR"
echo "      docker build -t localhost:5000/$SERVICE_NAME:v1 ."
echo "      docker push localhost:5000/$SERVICE_NAME:v1"
echo "   3. Deploy to cluster:"
echo "      kubectl apply -k $SERVICE_DIR/k8s/"
echo "   4. Verify canary status:"
echo "      kubectl get canary $SERVICE_NAME -n $SERVICE_NAME"
echo "   5. Test canary deployment by updating image version"
echo ""
echo "🔧 Monitoring level: $MONITORING_LEVEL"
if [ "$MONITORING_LEVEL" = "enhanced" ]; then
    echo "   ✅ PodMonitor included for precise metrics"
    echo "   ✅ Traffic-based success rate metric available"
    echo "   ✅ Enhanced canary vs primary comparison"
else
    echo "   ℹ️  Basic monitoring (faster deployment)"
    echo "   💡 Use 'enhanced' for production services"
fi
echo ""
echo "🔧 Customization points:"
echo "   - Update functional tests in $SERVICE_DIR/k8s/canary.yaml"
echo "   - Adjust resource limits in $SERVICE_DIR/k8s/base.yaml"
echo "   - Modify health check logic in $SERVICE_DIR/server.js"
echo "   - Update success rate/latency thresholds as needed"
echo ""
echo "📊 Monitor progress:"
echo "   - Grafana multi-app dashboard: http://localhost:3001"
echo "   - Canary status: kubectl get canary $SERVICE_NAME -n $SERVICE_NAME -w"
echo "   - Pod status: kubectl get pods -n $SERVICE_NAME"