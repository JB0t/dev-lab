# registry

<!-- docgen:begin id=config/registry:overview scope=config/registry hash=730e62dc40e3 -->
This module defines the configuration for a Docker registry setup within a Kubernetes cluster, including both the registry service and its associated UI. It consists of two main configuration files: one for the registry UI and another for the core registry deployment, each defining Kubernetes manifests for Deployments, Services, and Ingress resources.

The registry UI deployment runs a containerized UI application that provides a web interface for managing the registry, with configurations for environment variables that control its behavior such as enabling image deletion and setting the registry URL. The UI is exposed via an Ingress resource with a specific host and path.

The registry deployment runs a single instance of the official `registry:2.8` image, configured to run only on the control-plane node using a `Recreate` deployment strategy. It uses a `hostPath` volume to persist data and a ConfigMap for its configuration, exposing port 5000 for both internal and external access. The configuration includes settings for storage, health checks, and HTTP headers.
<!-- docgen:end id=config/registry:overview -->

<!-- docgen:begin id=config/registry:reference scope=config/registry hash=730e62dc40e3 -->
## Reference

### `registry-ui.yaml`

- **`Deployment/docker-registry-ui`** (manifest)
- **`Service/docker-registry-ui`** (manifest)
- **`Ingress/docker-registry-ui`** (manifest)

### `registry.yaml`

- **`ConfigMap/registry-config`** (manifest)
- **`Deployment/docker-registry`** (manifest)
- **`Service/docker-registry`** (manifest)
<!-- docgen:end id=config/registry:reference -->
