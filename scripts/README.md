# scripts

<!-- docgen:begin id=scripts:overview scope=scripts hash=f8ef1a611a48 -->
This module contains a collection of bash scripts for managing a development lab environment with Kubernetes, GitOps, and canary deployments. The scripts handle end-to-end workflows from initial setup through deployment and testing, with supporting utilities for prerequisites, timing analysis, and service management.

The module implements two primary deployment methodologies: GitOps-based using Flux CD and traditional script-based deployments. It includes bootstrap scripts for cluster initialization, GitOps deployment scripts for automated infrastructure management, and traditional deployment scripts for direct kubectl/helm operations. Additional scripts support canary deployments, environment testing, and infrastructure validation.

The scripts work together through shared functions for logging, error handling, and environment checks, with timing analysis and performance monitoring capabilities. They manage the complete lifecycle of services including creation, deployment, testing, and validation, while providing tools for version management, secret handling, and infrastructure reconciliation.
<!-- docgen:end id=scripts:overview -->

<!-- docgen:begin id=scripts:reference scope=scripts hash=f8ef1a611a48 -->
## Reference

### `analyze-timing.sh`

- **`analyze-timing.sh`** (script): Dev Lab Timing Analysis Script Analyzes timing history and shows performance trends
- **`format_duration`** (function): Function to format duration

### `bootstrap.sh`

- **`bootstrap.sh`** (script): Dev Lab Bootstrap Script Common initialization steps required for both script-based and GitOps deployments This script handles: cluster creation and basic setup only
- **`log`** (function): Logging functions
- **`success`** (function)
- **`warn`** (function)
- **`error`** (function)
- **`info`** (function)
- **`section`** (function)
- **`command_exists`** (function): Check if command exists
- **`check_prerequisites`** (function): Check prerequisites
- **`create_cluster`** (function): Create KinD cluster with proper configuration
- **`setup_registry`** (function): NOTE: Registry setup moved to deploy-traditional.sh for script-based deployments and to GitOps infrastructure/container-registry/ component for GitOps deployments
- **`setup_metrics_server`** (function): Setup metrics server
- **`show_bootstrap_info`** (function): Display bootstrap completion info
- **`cleanup`** (function): Cleanup function
- **`main`** (function): Main bootstrap function

### `create-canary-service.sh`

- **`create-canary-service.sh`** (script): scripts/create-canary-service.sh Generate a new canary-enabled service with all required components
- **`next`** (function)

### `create-flux-secrets.sh`

- **`create-flux-secrets.sh`** (script): Quick script to create Flux secrets from SSH keys This creates the Kubernetes secrets needed for GitRepository authentication
- **`log`** (function)
- **`success`** (function)
- **`warn`** (function)
- **`error`** (function)
- **`ensure_keys_exist`** (function): Check if keys exist, generate if not
- **`create_main_secret`** (function): Create main repository secret
- **`create_service_mesh_secret`** (function): Create service mesh layer secret
- **`check_prerequisites`** (function): Check prerequisites
- **`cleanup`** (function): Cleanup function
- **`main`** (function): Main function

### `cycle-lab.sh`

- **`cycle-lab.sh`** (script): Dev Lab Cycle Script - Full Bootstrap + GitOps Deployment with Timing This script runs the complete cycle and provides detailed timing breakdown
- **`format_duration`** (function): Function to format duration

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
- **`generate_deploy_key`** (function): Generate SSH deploy keys
- **`create_flux_secret`** (function): Create Flux system secrets
- **`show_deploy_key`** (function): Display deploy keys for GitHub setup
- **`create_git_source`** (function): Create GitRepository sources
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
- **`command_exists`** (function): Check if command exists
- **`install_linkerd_cli`** (function): Install Linkerd CLI if needed
- **`setup_linkerd`** (function): Setup Linkerd service mesh
- **`setup_registry`** (function): Setup local registry for traditional deployment
- **`check_bootstrap`** (function): Check if bootstrap was completed
- **`install_nginx_ingress`** (function): Install NGINX Ingress Controller
- **`deploy_monitoring`** (function): Deploy monitoring stack using Helm
- **`show_access_info`** (function): Show access information
- **`main`** (function): Main function

### `generate-canary-dashboards.sh`

- **`generate-canary-dashboards.sh`** (script): Multi-Application Canary Dashboard Generator This script discovers canary deployments and creates/updates dashboards

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

### `test-canary-deployment.sh`

- **`test-canary-deployment.sh`** (script): Canary Deployment Test Script This script triggers canary deployments for testing dashboard functionality

### `test-environment.sh`

- **`log`** (function): Logging functions
- **`success`** (function)
- **`error`** (function)
- **`warn`** (function)

### `update-service-image.sh`

- **`update-service-image.sh`** (script): scripts/update-service-image.sh Update service image version and trigger canary deployment

### `validate-canary-service.sh`

- **`validate-canary-service.sh`** (script): scripts/validate-canary-service.sh Validate that a canary-enabled service meets all requirements

### `version-info.sh`

- **`version-info.sh`** (script): Dev Lab Version Management Script This script helps with manual version management and provides information about the semver process
- **`get_current_version`** (function): Function to get current version
- **`show_version_info`** (function): Function to show version info
- **`show_versioning_rules`** (function): Function to show versioning rules
- **`simulate_bump`** (function): Function to simulate version bump
- **`show_recent_releases`** (function): Function to show recent releases
- **`validate_current_branch`** (function): Function to validate current branch
- **`main`** (function): Main function
<!-- docgen:end id=scripts:reference -->
