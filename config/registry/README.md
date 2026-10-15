# registry

<!-- docgen:begin id=config/registry:overview scope=config/registry hash=2261edbdeb8b -->
This module defines Kubernetes manifests for a private Docker registry setup. It includes a DaemonSet to run the registry service on each node and a Deployment for a web UI to manage the registry. The registry uses a ConfigMap for its configuration and stores data in a hostPath volume.

The DaemonSet runs the `registry:2.8` image with specific resource limits and node selection for amd64 architecture. It mounts a config map and a host path volume for data persistence. The Service exposes the registry on port 5000.

The UI Deployment runs the `joxit/docker-registry-ui:2.5.7` image with environment variables to configure it to talk to the registry service. It exposes a NodePort service on port 80 to access the UI. The UI can delete images and shows catalog information.

Both manifests live in the `dev-lab-registry` namespace. The registry stores data in `/tmp/dev-lab-registry` on each node. The UI connects to the registry via `http://docker-registry:5000`.
<!-- docgen:end id=config/registry:overview -->

<!-- docgen:begin id=config/registry:reference scope=config/registry hash=2261edbdeb8b -->
## Reference

### `registry-daemonset.yaml`

- **`ConfigMap/registry-config`** (manifest)
- **`DaemonSet/docker-registry`** (manifest)
- **`Service/docker-registry`** (manifest)

### `registry-ui.yaml`

- **`Deployment/docker-registry-ui`** (manifest)
- **`Service/docker-registry-ui`** (manifest)
<!-- docgen:end id=config/registry:reference -->
