# scripts

<!-- docgen:begin id=scripts:overview scope=scripts hash=019c1c2adcb3 -->
Scripts module provides bash automation for Dev Lab environment setup and deployment. It contains multiple scripts for different phases of the development environment lifecycle. The bootstrap script initializes the KinD cluster, installs Linkerd service mesh, sets up local registry, and configures basic infrastructure. The deploy-gitops script uses Flux CD for automated GitOps deployments after bootstrap. The deploy-traditional script installs infrastructure components directly using kubectl and Helm commands. The install-prerequisites script handles installation of required tools like Docker, kubectl, Helm, KinD, and jq. The test-environment script validates the complete environment setup and runs basic functionality tests. All scripts share common logging functions and follow consistent error handling patterns. Each script operates in sequence: prerequisites → bootstrap → deployment method → testing. The module supports both traditional script-based deployment and GitOps deployment approaches for the same development environment.
<!-- docgen:end id=scripts:overview -->

<!-- docgen:begin id=scripts:reference scope=scripts hash=019c1c2adcb3 -->
## Reference

### `bootstrap.sh`

- **`bootstrap.sh`** (script): Dev Lab Bootstrap Script Common initialization steps required for both script-based and GitOps deployments This script handles: cluster creation, Linkerd, registry, and basic setup
- **`log`** (function): Logging functions
- **`success`** (function)
- **`warn`** (function)
- **`error`** (function)
- **`info`** (function)
- **`section`** (function)
- **`command_exists`** (function): Check if command exists
- **`check_prerequisites`** (function): Check prerequisites
- **`install_linkerd_cli`** (function): Install Linkerd CLI if needed
- **`create_cluster`** (function): Create KinD cluster with proper configuration
- **`setup_linkerd`** (function): Setup Linkerd service mesh
- **`setup_registry`** (function): Setup local registry
- **`setup_metrics_server`** (function): Setup metrics server
- **`show_bootstrap_info`** (function): Display bootstrap completion info
- **`cleanup`** (function): Cleanup function
- **`main`** (function): Main bootstrap function

### `deploy-gitops.sh`

- **`deploy-gitops.sh`** (script): Dev Lab GitOps Deployment Script GitOps deployment method (post-bootstrap) Sets up Flux CD for automated infrastructure and application deployment
- **`log`** (function): Logging functions
- **`success`** (function)
- **`warn`** (function)
- **`error`** (function)
- **`info`** (function)
- **`section`** (function)
- **`check_bootstrap`** (function): Check if bootstrap was completed
- **`install_flux_cli`** (function): Install Flux CLI if not present
- **`install_flux_controllers`** (function): Install Flux controllers
- **`generate_deploy_key`** (function): Generate SSH deploy key
- **`create_flux_secret`** (function): Create Flux system secret
- **`show_deploy_key`** (function): Display deploy key for GitHub setup
- **`create_git_source`** (function): Create GitRepository source
- **`apply_git_kustomizations`** (function): Apply Git-managed kustomizations
- **`wait_for_deployment`** (function): Wait for deployment completion
- **`show_gitops_info`** (function): Show GitOps status and access info
- **`cleanup`** (function): Cleanup function
- **`main`** (function): Main function

### `deploy-traditional.sh`

- **`deploy-traditional.sh`** (script): Dev Lab Traditional Deployment Script Script-based deployment method (post-bootstrap) Installs infrastructure components using direct kubectl/helm commands
- **`log`** (function): Logging functions
- **`success`** (function)
- **`warn`** (function)
- **`error`** (function)
- **`info`** (function)
- **`section`** (function)
- **`check_bootstrap`** (function): Check if bootstrap was completed
- **`install_nginx_ingress`** (function): Install NGINX Ingress Controller
- **`deploy_monitoring`** (function): Deploy monitoring stack using Helm
- **`show_access_info`** (function): Show access information
- **`main`** (function): Main function

### `install-prerequisites.sh`

- **`install-prerequisites.sh`** (script): Dev Lab Prerequisites Installation Script Installs required tools for dev-lab environment
- **`log`** (function)
- **`success`** (function)
- **`warn`** (function)
- **`error`** (function)
- **`command_exists`** (function): Check if command exists
- **`detect_os`** (function): Detect OS and package manager
- **`install_docker`** (function): Install Docker
- **`install_kubectl`** (function): Install kubectl
- **`install_helm`** (function): Install Helm
- **`install_kind`** (function): Install KinD
- **`install_jq`** (function): Install jq
- **`main`** (function): Main installation function

### `test-environment.sh`

- **`log`** (function): Logging functions
- **`success`** (function)
- **`error`** (function)
- **`warn`** (function)
<!-- docgen:end id=scripts:reference -->
