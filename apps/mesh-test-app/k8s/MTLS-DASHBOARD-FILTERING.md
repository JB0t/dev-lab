# mTLS Security Status Dashboard Updates

## Problem
The mTLS Security Status panel was including health check traffic, which created "noise" in the metrics. Health checks (like `/health/live`, `/health/ready`, `/metrics`) are infrastructure traffic and don't represent actual application communication that should be secured with mTLS.

## Solution
Updated the Prometheus queries in two dashboard panels to filter out health check traffic:

### 1. mTLS Security Status Panel (ID: 11)

**Before:**
```promql
sum(rate(response_total{namespace="mesh-test",direction="inbound",tls="true",dst_service_name!~".*health.*"}[1m])) / sum(rate(response_total{namespace="mesh-test",direction="inbound",dst_service_name!~".*health.*"}[1m])) * 100
```

**After:**
```promql
sum(rate(response_total{namespace="mesh-test",direction="inbound",tls="true",target_port="3000",path!~"/health.*|/live|/ready|/metrics",status_code!~"404"}[1m])) / sum(rate(response_total{namespace="mesh-test",direction="inbound",target_port="3000",path!~"/health.*|/live|/ready|/metrics",status_code!~"404"}[1m])) * 100
```

### 2. TLS Connection Breakdown Panel (ID: 12)

**Before:**
```promql
sum(rate(response_total{namespace="mesh-test",direction="inbound"}[1m])) by (tls)
```

**After:**
```promql
sum(rate(response_total{namespace="mesh-test",direction="inbound",target_port="3000",path!~"/health.*|/live|/ready|/metrics",status_code!~"404"}[1m])) by (tls)
```

## Filters Applied

1. **`target_port="3000"`** - Only application traffic (excludes admin/health ports)
2. **`path!~"/health.*|/live|/ready|/metrics"`** - Excludes:
   - `/health/*` - All health endpoints
   - `/live` - Liveness probes  
   - `/ready` - Readiness probes
   - `/metrics` - Prometheus scraping
3. **`status_code!~"404"`** - Excludes 404 errors (often from health check misconfigurations)

## Expected Result

- **mTLS Security Status** should now show closer to 100% for application traffic
- **TLS Connection Breakdown** will only show actual app communication patterns
- Health check "noise" is eliminated from mTLS coverage calculations

## Verification

You can verify the filtering is working by comparing:

```bash
# All traffic (including health checks)
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mesh-test\",direction=\"inbound\"}[1m]))"

# Filtered app traffic only  
curl -s "http://localhost:9091/api/v1/query?query=sum(rate(response_total{namespace=\"mesh-test\",direction=\"inbound\",target_port=\"3000\",path!~\"/health.*|/live|/ready|/metrics\",status_code!~\"404\"}[1m]))"
```

The filtered query should show significantly less traffic, representing only genuine application communication.