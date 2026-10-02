# k8s

<!-- docgen:begin id=apps/mtls-test-app/k8s:overview scope=apps/mtls-test-app/k8s hash=9cb8a2d45843 -->
This module defines Kubernetes manifests for a test environment that demonstrates the difference between plain HTTP communication and mTLS-enabled communication. It creates two separate namespaces, `mtls-test-plain` and `mtls-test-secure`, to isolate test workloads with and without Linkerd service mesh injection. The plain namespace does not have the `linkerd.io/inject` annotation, while the secure namespace does, enabling sidecar injection for mTLS.

The module includes two identical test applications, each deployed as a `Deployment` with a corresponding `Service`. The applications use the same container image but are configured with different UI colors to visually distinguish their environments. The `test-app-plain` deployment runs without a sidecar, while `test-app-secure` includes a Linkerd sidecar that handles mTLS communication.

The manifests are structured to support automated testing using a companion script that creates ephemeral curl pods for connectivity testing between the two environments. The configuration allows for clear demonstration of how mTLS affects network communication between services, with the secure namespace enabling encrypted and authenticated traffic through the Linkerd proxy sidecars.
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
