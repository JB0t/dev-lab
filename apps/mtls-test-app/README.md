# Standalone mTLS Testing

This directory contains a **standalone mTLS demonstration** that doesn't depend on any existing infrastructure or loadtester pods.

## Files

- **`mtls-test.yaml`** - Creates two test environments:
  - `mtls-test-plain` namespace (NO Linkerd injection)
  - `mtls-test-secure` namespace (WITH Linkerd injection)
  - Test applications in both namespaces for comparison

- **`test-mtls.sh`** - Automated test script that:
  - Uses ephemeral curl pods for testing (no dependencies)
  - Demonstrates mTLS vs plain HTTP communication
  - Shows Prometheus metrics (if available)
  - Automatically handles Linkerd injection for test pods

## Usage

### 1. Deploy Test Environment

```bash
kubectl apply -f k8s/mtls-test.yaml
```

### 2. Wait for Pods to be Ready

```bash
kubectl get pods -n mtls-test-plain -n mtls-test-secure
```

### 3. Run mTLS Test

```bash
./scripts/test-mtls.sh
```

### 4. Optional: Set up Prometheus Port-Forward

For metrics visualization:

```bash
kubectl port-forward -n linkerd-viz svc/prometheus 9091:9090
```

### 5. Cleanup

```bash
kubectl delete namespace mtls-test-plain mtls-test-secure
```

## What the Test Shows

- **Plain HTTP**: Requests between pods without Linkerd sidecars (no encryption)
- **mTLS**: Requests between pods with Linkerd sidecars (automatic mutual TLS)
- **Metrics**: Prometheus metrics showing `tls=no_identity` vs `tls=true`

## Expected Output

The script will show:

1. Successful connections to both plain and secure services
2. Traffic generation for metrics
3. Prometheus metrics showing mTLS status differences
4. Summary of the mTLS demonstration

The key difference you'll see is in the Prometheus metrics:

- Plain namespace: `tls=no_identity`
- Secure namespace: `tls=true`
