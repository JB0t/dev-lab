# scripts

<!-- docgen:begin id=apps/mtls-test-app/scripts:overview scope=apps/mtls-test-app/scripts hash=753286d96405 -->
This module provides a bash script for testing and demonstrating mTLS (mutual Transport Layer Security) behavior within a Kubernetes environment using Linkerd service mesh. It automates the process of creating ephemeral test pods to make HTTP requests to services in different namespaces, one configured for plain HTTP and another with mTLS enabled through Linkerd injection.

The script includes a `run_curl_test` function that dynamically determines whether to inject Linkerd sidecars into test pods based on namespace annotations, then executes curl commands to target specific services. It also performs checks against Prometheus metrics to validate mTLS status by querying response rates and TLS identity information from the Linkerd metrics endpoint.

The test workflow first validates mTLS behavior by making requests to services in both a plain namespace (without Linkerd injection) and a secure namespace (with Linkerd injection). It then queries Prometheus to verify that traffic in each namespace shows the expected TLS status, providing clear visual confirmation of mTLS enforcement. The script concludes with instructions for cleanup and notes on accessing Grafana dashboards for ongoing monitoring.
<!-- docgen:end id=apps/mtls-test-app/scripts:overview -->

<!-- docgen:begin id=apps/mtls-test-app/scripts:reference scope=apps/mtls-test-app/scripts hash=753286d96405 -->
## Reference

### `test-mtls.sh`

- **`run_curl_test`** (function): Function to run curl commands in ephemeral pods
<!-- docgen:end id=apps/mtls-test-app/scripts:reference -->
