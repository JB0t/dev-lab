# networking

<!-- docgen:begin id=infrastructure/networking:overview scope=infrastructure/networking hash=cb5af939ee4c -->
This module provides the configuration for deploying an NGINX Ingress Controller in a Kubernetes cluster, specifically optimized for use with KinD (Kubernetes in Docker). It defines all necessary Kubernetes resources to run the ingress controller, including its deployment, service, service account, and associated RBAC rules.

The module consists of two main files: `ingress-nginx.yaml` which contains the full set of Kubernetes manifests for the ingress controller and its dependencies, and `kustomization.yaml` which serves as a Kustomize configuration to apply these resources in the `ingress-nginx` namespace. The manifests include a `Deployment` for the controller, a `Service` to expose it, `ServiceAccount` and `RoleBinding`/`ClusterRoleBinding` for permissions, and a `ConfigMap` for controller configuration.

The `kustomization.yaml` file references the main manifest file and applies it within the `ingress-nginx` namespace, ensuring consistent deployment of the ingress controller setup across different environments. The controller is configured with specific tolerations and node selectors to ensure it runs on nodes marked with `ingress-ready=true` and is optimized for the KinD development environment.
<!-- docgen:end id=infrastructure/networking:overview -->

<!-- docgen:begin id=infrastructure/networking:reference scope=infrastructure/networking hash=cb5af939ee4c -->
## Reference

### `ingress-nginx.yaml`

- **`Namespace/ingress-nginx`** (manifest)
- **`Deployment/ingress-nginx-controller`** (manifest)
- **`Service/ingress-nginx-controller`** (manifest)
- **`ServiceAccount/ingress-nginx`** (manifest)
- **`ConfigMap/ingress-nginx-controller`** (manifest)
- **`ClusterRole/ingress-nginx`** (manifest)
- **`ClusterRoleBinding/ingress-nginx`** (manifest)
- **`Role/ingress-nginx`** (manifest)
- **`RoleBinding/ingress-nginx`** (manifest)
- **`IngressClass/nginx`** (manifest)

### `kustomization.yaml`

- **`Kustomization/dev-lab-networking`** (manifest)
<!-- docgen:end id=infrastructure/networking:reference -->
