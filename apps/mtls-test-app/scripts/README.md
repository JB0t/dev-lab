# scripts

<!-- docgen:begin id=apps/mtls-test-app/scripts:overview scope=apps/mtls-test-app/scripts hash=e851f29c40ab -->
This module runs mTLS demonstration tests using ephemeral Kubernetes pods. It tests HTTP connections to services in different namespaces with and without Linkerd injection. The script creates temporary curl pods to make requests and checks if mTLS is active.

The main function `run_curl_test` creates ephemeral pods with or without Linkerd sidecar injection based on namespace annotations. It runs curl commands against test services and shows response headers. The script tests both plain HTTP and mTLS connections to show the difference.

The script checks Prometheus metrics to verify mTLS status. It generates test traffic and queries Prometheus for response rates grouped by TLS status. It reports if connections show `tls=no_identity` or `tls=true`. The script ends with cleanup instructions for the test namespaces.
<!-- docgen:end id=apps/mtls-test-app/scripts:overview -->

<!-- docgen:begin id=apps/mtls-test-app/scripts:reference scope=apps/mtls-test-app/scripts hash=e851f29c40ab -->
## Reference

### `test-mtls.sh`

- **`run_curl_test`** (function): Function to run curl commands in ephemeral pods
<!-- docgen:end id=apps/mtls-test-app/scripts:reference -->
