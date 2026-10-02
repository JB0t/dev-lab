# scripts

<!-- docgen:begin id=apps/order-service/scripts:overview scope=apps/order-service/scripts hash=105318c6914c -->
This module provides a bash script for building and deploying the Order Service container image. The script automates the process of creating a Docker image with a specific registry, image name, and version, then pushes it to a local registry for deployment.

The script follows a standard container build workflow using `docker build` and `docker push` commands. It sets up environment variables for the registry, image name, and version, then executes the build and push operations with error handling enabled through `set -e`.

The build script is designed to work in conjunction with Kubernetes deployment configurations located in the `k8s/` directory. After building and pushing the image, it provides instructions for deploying the service using `kubectl apply -k k8s/` and for performing canary deployments by updating image tags and environment variables in the Kubernetes configuration files.
<!-- docgen:end id=apps/order-service/scripts:overview -->

<!-- docgen:begin id=apps/order-service/scripts:reference scope=apps/order-service/scripts hash=105318c6914c -->
## Reference

### `build.sh`

- **`build.sh`** (script): Order Service Build and Deploy Script
<!-- docgen:end id=apps/order-service/scripts:reference -->
