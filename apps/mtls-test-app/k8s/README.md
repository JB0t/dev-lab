# k8s

<!-- docgen:begin id=apps/mtls-test-app/k8s:overview scope=apps/mtls-test-app/k8s hash=9cb8a2d45843 -->
This module defines Kubernetes manifests for a test setup that demonstrates mTLS behavior differences. It creates two namespaces with different Linkerd injection settings. One namespace has no injection and the other has `linkerd.io/inject: enabled` annotation.

The module exports six manifests organized into two test environments. Each environment includes a Deployment and Service for a test application. The plain environment runs without Linkerd sidecar. The secure environment runs with Linkerd sidecar injected.

Manifests use standard Kubernetes v1 and apps/v1 API versions. The test applications use the same `ghcr.io/stefanprodan/podinfo:6.4.0` image but with different UI colors to distinguish them visually. The `test-mtls.sh` script uses these manifests to create ephemeral test pods.
<!-- docgen:end id=apps/mtls-test-app/k8s:overview -->

<!-- docgen:begin id=apps/mtls-test-app/k8s:reference scope=apps/mtls-test-app/k8s hash=9cb8a2d45843 -->
## Reference

### `mtls-test.yaml`

- **`Namespace/mtls-test-plain`** (manifest)
- **`Namespace/mtls-test-secure`** (manifest)
- **`Deployment/test-app-plain`** (manifest)
- **`Service/test-app-plain-svc`** (manifest)
- **`Deployment/test-app-secure`** (manifest)
- **`Service/test-app-secure-svc`** (manifest)
<!-- docgen:end id=apps/mtls-test-app/k8s:reference -->
