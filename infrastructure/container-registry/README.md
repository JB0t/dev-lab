# container-registry

<!-- docgen:begin id=infrastructure/container-registry:overview scope=infrastructure/container-registry hash=065f4413e0b0 -->
This module defines a container registry setup for a development lab environment. It uses Kustomize to manage Kubernetes manifests for deploying a Docker registry and its web UI. The registry runs as a DaemonSet on control-plane nodes with host network access. It stores images on the host filesystem under `/var/lib/registry`.

The module includes a ConfigMap with registry configuration that enables image deletion and sets up HTTP headers for security. A ClusterIP service exposes the registry internally on port 5000. The web UI runs as a Deployment with a NodePort service and an Ingress rule that makes it accessible at `registry.dev-lab.local:5001`.

The Kustomization file ties everything together under the `dev-lab-registry` namespace. It references the main manifest file and sets the namespace for all resources. The setup uses standard Kubernetes primitives with Flux labels for management. The registry UI supports image deletion and shows catalog information. The Ingress uses the nginx ingress class with rewrite rules. The registry configuration disables access logs and sets log level to warn. The UI uses a specific Docker image version and configures proxy pass to the registry service.
<!-- docgen:end id=infrastructure/container-registry:overview -->

<!-- docgen:begin id=infrastructure/container-registry:reference scope=infrastructure/container-registry hash=065f4413e0b0 -->
## Reference

### `docker-registry.yaml`

- **`Namespace/dev-lab-registry`** (manifest)
- **`DaemonSet/docker-registry`** (manifest)
- **`ConfigMap/registry-config`** (manifest)
- **`Service/docker-registry`** (manifest)
- **`Deployment/docker-registry-ui`** (manifest)
- **`Service/docker-registry-ui`** (manifest)
- **`Ingress/registry-ui-ingress`** (manifest)

### `kustomization.yaml`

- **`Kustomization/dev-lab-registry`** (manifest)
<!-- docgen:end id=infrastructure/container-registry:reference -->
