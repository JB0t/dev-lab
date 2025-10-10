# Production Canary Service Setup Guide

This guide provides templates, scripts, and procedures for converting any service to use Flagger canary deployments in the dev-lab environment.

## Quick Reference

### Infrastructure Requirements

- Linkerd service mesh (provides metrics and traffic splitting)
- Flagger progressive delivery controller
- Prometheus monitoring stack
- Flux GitOps (for automated deployments)

### Application Requirements

- Health endpoints (`/health/live`, `/health/ready`)
- Graceful shutdown handling (SIGTERM)
- Resource limits defined
- Named ports in services
- Version labels and environment variables
- Graceful deployment rollout strategy (`updateStrategy`, `podDisruptionBudget`, etc)

## Service Conversion Checklist

### Phase 1: Application Preparation

- [ ] Add health check endpoints
- [ ] Implement graceful shutdown
- [ ] Add request logging (recommended)
- [ ] Define resource requirements
- [ ] Test application locally

### Phase 2: Kubernetes Resources

- [ ] Inject linkerd-proxy
- [ ] Deploy any additional app labels
- [ ] Deploy flagger-loadtester
- [ ] Create metric templates
- [ ] **Choose monitoring level** (basic vs enhanced)
- [ ] Deploy canary configuration

### Phase 3: Verification

- [ ] Verify 2/2 pod readiness (app + linkerd sidecar)
- [ ] Check canary status: "Initialized"
- [ ] Test canary deployment with version update
- [ ] Monitor in Grafana dashboards

## Monitoring Strategy

### Basic vs Enhanced Monitoring

**Basic Monitoring** (Default):

- Standard success rate and latency metrics
- Faster deployment and simpler maintenance
- Suitable for development and non-critical services
- Less precise canary evaluation

**Enhanced Monitoring** (Production Recommended):

- Application-specific PodMonitor for precise metrics
- Traffic-based success rate (canary vs primary comparison)
- More accurate rollback decisions
- Better troubleshooting capabilities
- Slightly more complex setup

### When to Use Enhanced Monitoring

**Production/Critical Services:**

- User-facing applications
- High-traffic services
- Services requiring precise canary evaluation
- Complex traffic patterns

**Development/Internal Services:**

- Internal tools
- Development environments
- Simple traffic patterns
- Rapid prototyping

## Templates

### Required supplemental services

```text
k8s/
  ├── base.yaml           # Main deployment and service
  ├── canary.yaml         # Flagger canary configuration
  ├── loadtester.yaml     # Flagger loadtester
  ├── metrics.yaml        # Prometheus metric templates
  └── podmonitor.yaml     # Optional: Enhanced monitoring
```

### Template 1: Base Deployment (`k8s/base.yaml`)

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: {{SERVICE_NAME}}
  labels:
    name: {{SERVICE_NAME}}
  annotations:
    linkerd.io/inject: enabled

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{SERVICE_NAME}}
  namespace: {{SERVICE_NAME}}
  labels:
    app: {{SERVICE_NAME}}
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
      app: {{SERVICE_NAME}}
      version: v1
  template:
    metadata:
      labels:
        app: {{SERVICE_NAME}}
        version: v1
    spec:
      containers:
      - name: {{SERVICE_NAME}}
        image: localhost:5000/{{SERVICE_NAME}}:v1
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: {{PORT}}
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
            port: {{PORT}}
          initialDelaySeconds: 30
          periodSeconds: 10
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health/ready
            port: {{PORT}}
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
  name: {{SERVICE_NAME}}
  namespace: {{SERVICE_NAME}}
  labels:
    app: {{SERVICE_NAME}}
spec:
  selector:
    app: {{SERVICE_NAME}}
  ports:
  - port: 80
    targetPort: {{PORT}}
    name: http
  type: ClusterIP

---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{SERVICE_NAME}}-ingress
  namespace: {{SERVICE_NAME}}
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: {{SERVICE_NAME}}.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: {{SERVICE_NAME}}
            port:
              number: 80
```

### Template 2: Canary Configuration (`k8s/canary.yaml`)

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: {{SERVICE_NAME}}
  namespace: {{SERVICE_NAME}}
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{SERVICE_NAME}}
  
  service:
    port: 80
    targetPort: {{PORT}}
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
        namespace: {{SERVICE_NAME}}
      thresholdRange:
        min: 97
      interval: 1m
    
    - name: latency
      templateRef:
        name: linkerd-request-duration
        namespace: {{SERVICE_NAME}}
      thresholdRange:
        max: 300
      interval: 1m
    
    webhooks:
    # Basic health check
    - name: {{SERVICE_NAME}}-health-check
      url: http://flagger-loadtester.{{SERVICE_NAME}}/
      timeout: 15s
      type: pre-rollout
      metadata:
        type: bash
        cmd: |
          curl -sf http://{{SERVICE_NAME}}-canary.{{SERVICE_NAME}}/health/live > /dev/null &&
          curl -sf http://{{SERVICE_NAME}}-canary.{{SERVICE_NAME}}/health/ready > /dev/null
    
    # Load testing
    - name: {{SERVICE_NAME}}-load-test
      url: http://flagger-loadtester.{{SERVICE_NAME}}/
      timeout: 30s
      metadata:
        type: cmd
        cmd: "hey -z 25s -q 8 -c 2 -H 'User-Agent: Flagger-{{SERVICE_NAME}}' http://{{SERVICE_NAME}}-canary.{{SERVICE_NAME}}/"
    
    # Custom functional test (customize per service)
    - name: {{SERVICE_NAME}}-functional-test
      url: http://flagger-loadtester.{{SERVICE_NAME}}/
      timeout: 20s
      type: pre-rollout
      metadata:
        type: bash
        cmd: |
          # Basic endpoint test
          response=$(curl -sf http://{{SERVICE_NAME}}-canary.{{SERVICE_NAME}}/)
          echo "$response" | grep -q "{{SERVICE_NAME}}"
```

### Template 3: Loadtester (`k8s/loadtester.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagger-loadtester
  namespace: {{SERVICE_NAME}}
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
  namespace: {{SERVICE_NAME}}
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
```

### Template 4: Metric Templates (`k8s/metrics.yaml`)

**Basic Monitoring Version:**

```yaml
---
# Basic Linkerd Success Rate Metric Template
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: linkerd-success-rate
  namespace: {{SERVICE_NAME}}
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
          target_port="{{PORT}}",
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
          target_port="{{PORT}}"
        }[{{ interval }}]
      )
    ) * 100

---
# Basic Linkerd Request Duration Metric Template
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: linkerd-request-duration
  namespace: {{SERVICE_NAME}}
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
            target_port="{{PORT}}"
          }[{{ interval }}]
        )
      ) by (le)
    )
```

### Template 5: Enhanced Monitoring (`k8s/podmonitor.yaml`)

**For Production/Critical Services - Add this for enhanced monitoring:**

```yaml
---
# Application-specific PodMonitor for Enhanced Canary Metrics
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: {{SERVICE_NAME}}-linkerd-proxy
  namespace: {{SERVICE_NAME}}
  labels:
    app: {{SERVICE_NAME}}
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: {{SERVICE_NAME}}
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
```

**Enhanced metrics.yaml addition:**

```yaml
---
# Advanced Traffic-based Success Rate (for canary vs primary comparison)
# Requires PodMonitor above for best accuracy
apiVersion: flagger.app/v1beta1
kind: MetricTemplate
metadata:
  name: linkerd-traffic-success-rate
  namespace: {{SERVICE_NAME}}
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
```

## Service Generation Script

Create and use this script to generate boilerplate for new services:

```bash
#!/bin/bash
# scripts/create-canary-service.sh

set -e

SERVICE_NAME="$1"
PORT="${2:-3000}"

if [ -z "$SERVICE_NAME" ]; then
    echo "Usage: $0 <service-name> [port]"
    echo "Example: $0 user-service 8080"
    exit 1
fi

echo "🚀 Creating canary-enabled service: $SERVICE_NAME (port: $PORT)"

# Create service directory structure
SERVICE_DIR="apps/$SERVICE_NAME"
mkdir -p "$SERVICE_DIR/k8s"

# Function to replace template variables
replace_template() {
    local template_file="$1"
    local output_file="$2"
    
    sed "s/{{SERVICE_NAME}}/$SERVICE_NAME/g; s/{{PORT}}/$PORT/g" "$template_file" > "$output_file"
}

# Generate Kubernetes manifests from templates
echo "📝 Generating Kubernetes manifests..."

replace_template "templates/base-template.yaml" "$SERVICE_DIR/k8s/base.yaml"
replace_template "templates/canary-template.yaml" "$SERVICE_DIR/k8s/canary.yaml"
replace_template "templates/loadtester-template.yaml" "$SERVICE_DIR/k8s/loadtester.yaml"
replace_template "templates/metrics-template.yaml" "$SERVICE_DIR/k8s/metrics.yaml"

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

// Health endpoints (REQUIRED)
app.get('/health/live', (req, res) => {
  res.status(200).json({ status: 'alive', service: '$SERVICE_NAME', version });
});

app.get('/health/ready', (req, res) => {
  res.status(200).json({ status: 'ready', service: '$SERVICE_NAME', version });
});

// Main endpoint
app.get('/', (req, res) => {
  res.json({
    service: '$SERVICE_NAME',
    version: version,
    message: '$SERVICE_NAME is running!',
    timestamp: new Date().toISOString()
  });
});

// Graceful shutdown (REQUIRED)
process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down gracefully');
  process.exit(0);
});

app.listen(port, () => {
  console.log(\`$SERVICE_NAME \${version} running on port \${port}\`);
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

# Create GitOps kustomization entry
echo "🔄 Adding GitOps configuration..."

KUSTOMIZATION_ENTRY="
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: dev-lab-$SERVICE_NAME
  namespace: flux-system
  labels:
    app.kubernetes.io/part-of: flux
spec:
  interval: 30s
  retryInterval: 1m
  sourceRef:
    kind: GitRepository
    name: dev-lab-repo
  path: \"./apps/$SERVICE_NAME\"
  prune: true
  wait: true
  timeout: 5m0s
  dependsOn:
    - name: dev-lab-service-mesh-layer
    - name: dev-lab-networking
    - name: dev-lab-prometheus
    - name: dev-lab-monitoring
    - name: dev-lab-registry
    - name: dev-lab-flagger"

echo "$KUSTOMIZATION_ENTRY" >> clusters/dev-lab/dev-lab-kustomizations.yaml

echo "Service $SERVICE_NAME created successfully!"
echo ""
echo "📋 Next steps:"
echo "   1. Review and customize the generated files in $SERVICE_DIR/"
echo "   2. Build and push the Docker image:"
echo "      cd $SERVICE_DIR"
echo "      docker build -t localhost:5000/$SERVICE_NAME:v1 ."
echo "      docker push localhost:5000/$SERVICE_NAME:v1"
echo "   3. Deploy to cluster:"
echo "      kubectl apply -f $SERVICE_DIR/k8s/"
echo "   4. Verify canary status:"
echo "      kubectl get canary $SERVICE_NAME -n $SERVICE_NAME"
echo "   5. Test canary deployment by updating image version"
echo ""
echo "🔧 Customization points:"
echo "   - Update functional tests in $SERVICE_DIR/k8s/canary.yaml"
echo "   - Adjust resource limits in $SERVICE_DIR/k8s/base.yaml"
echo "   - Modify health check logic in $SERVICE_DIR/server.js"
echo "   - Update success rate/latency thresholds as needed"
EOF

chmod +x scripts/create-canary-service.sh
```

## Known Issues & Solutions

### 1. **Test Dependencies**

- **Problem**: Tests fail due to missing tools (`jq`, specific curl versions)
- **Solution**: Use only basic bash/curl commands, avoid complex JSON parsing

```bash
# ❌ Avoid this (requires jq)
order_id=$(echo "$response" | jq -r '.id')

# Use this instead
if ! echo "$response" | grep -q '"id"'; then
    echo "Response missing ID field"
    exit 1
fi
```

### 2. **Traffic Requirements**

- **Problem**: Low-traffic services don't generate enough metrics
- **Solution**: Add load generation or increase analysis intervals

```yaml
# Add to canary webhooks for baseline traffic
- name: traffic-generator
  url: http://flagger-loadtester.{{SERVICE_NAME}}/
  metadata:
    type: cmd
    cmd: "hey -z 60s -q 2 -c 1 http://{{SERVICE_NAME}}-canary.{{SERVICE_NAME}}/"
```

### 3. **Resource Limits**

- **Problem**: Missing or incorrect resource limits cause OOM kills
- **Solution**: Always define appropriate limits, start conservative

```yaml
resources:
  requests:
    cpu: 50m      # Start small
    memory: 64Mi
  limits:
    cpu: 150m     # Allow some headroom
    memory: 128Mi
```

### 4. **Health Check Timing**

- **Problem**: Health checks fail during application startup
- **Solution**: Increase `initialDelaySeconds` for slower-starting apps

```yaml
livenessProbe:
  initialDelaySeconds: 60  # Increase for slow startup
  periodSeconds: 10
  failureThreshold: 3
```

### 5. **Dependency Handling**

- **Problem**: Applications fail when optional dependencies are unavailable
- **Solution**: Design for graceful degradation

```javascript
// ❌ Hard dependency
const redis = require('redis');
const client = redis.createClient(redisUrl);

// Optional dependency
let redisClient = null;
if (process.env.REDIS_URL) {
  try {
    redisClient = redis.createClient(process.env.REDIS_URL);
  } catch (error) {
    console.log('Redis unavailable, continuing without cache');
  }
}
```

## Monitoring & Dashboards

### Multi-Application Dashboard

The dev-lab includes a multi-application canary dashboard that automatically discovers new services. It provides:

- **Template Variables**: Select namespace and application dynamically
- **Cross-Service Comparison**: Success rates, latency, traffic patterns
- **Canary Status Overview**: Current weights and deployment states
- **mTLS Security Metrics**: Encryption coverage across services

### Adding Services to Monitoring

New services are automatically discovered if they:

1. Have Flagger canary configurations
2. Use Linkerd service mesh (proper injection)
3. Expose Prometheus metrics via Linkerd proxy

No additional dashboard configuration is required.

## GitOps Integration

### Automatic Deployment

Services created with the generator script are automatically managed by Flux:

1. **Git Commit**: Changes trigger Flux reconciliation
2. **Kustomization**: Each service has its own Flux Kustomization
3. **Dependencies**: Services wait for infrastructure components
4. **Monitoring**: Canary status is tracked and alerted

### Manual Operations

For manual canary operations:

```bash
# Trigger canary deployment
kubectl patch deployment SERVICE_NAME -n SERVICE_NAME -p '{"spec":{"template":{"spec":{"containers":[{"name":"SERVICE_NAME","image":"localhost:5000/SERVICE_NAME:v2"}]}}}}'

# Monitor progress
kubectl get canary SERVICE_NAME -n SERVICE_NAME -w

# Emergency rollback
kubectl rollout undo deployment/SERVICE_NAME -n SERVICE_NAME
```

## Testing & Validation

### Pre-Deployment Testing

```bash
# Validate Kubernetes manifests
kubectl apply --dry-run=client -f apps/SERVICE_NAME/k8s/

# Check resource requirements
kubectl top pods -n SERVICE_NAME

# Verify Linkerd injection
kubectl get pods -n SERVICE_NAME -o jsonpath='{.items[*].spec.containers[*].name}'
# Should show: SERVICE_NAME linkerd-proxy
```

### Post-Deployment Validation

```bash
# Check canary status
kubectl get canary SERVICE_NAME -n SERVICE_NAME

# Verify metrics collection
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090 &
# Query: response_total{namespace="SERVICE_NAME"}

# Test endpoints
kubectl run curl-test --image=curlimages/curl --rm -it --restart=Never -- curl -s http://SERVICE_NAME.SERVICE_NAME.svc.cluster.local/health/ready
```

## Quick Start Summary

1. **Generate service**: `./scripts/create-canary-service.sh my-service 8080`
2. **Customize application**: Edit `apps/my-service/server.js`
3. **Build and push**: `docker build/push localhost:5000/my-service:v1`
4. **Deploy**: `kubectl apply -f apps/my-service/k8s/`
5. **Verify**: `kubectl get canary my-service -n my-service`
6. **Test canary**: Update image version and apply
7. **Monitor**: View in Grafana multi-app dashboard

This guide provides everything needed to efficiently convert services to use canary deployments in the dev-lab environment.
