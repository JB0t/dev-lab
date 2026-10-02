# scripts

<!-- docgen:begin id=apps/mesh-test-app/scripts:overview scope=apps/mesh-test-app/scripts hash=bd8145acf6f0 -->
This module provides a collection of Bash scripts for managing service mesh testing environments, with a focus on canary deployments using Linkerd. It includes scripts for setting up the service mesh, deploying canary versions of applications, monitoring traffic distribution, and running comprehensive test suites. The scripts handle various deployment strategies including TrafficSplit-based canaries and HTTPRoute-based traffic routing.

The module's core functionality is organized into four main scripts that work together to create a complete testing workflow. The `setup-service-mesh.sh` script initializes the Linkerd service mesh environment, installs required CRDs, and deploys the test application with initial canary configurations. The `linkerd-canary.sh` script provides advanced canary deployment capabilities using Linkerd's native features like HTTPRoute and header-based routing. The `canary-deploy.sh` script offers traditional canary management with traffic weight adjustments and deployment lifecycle operations. Finally, `test-suite.sh` automates end-to-end testing of the service mesh setup including zero-downtime deployments and mTLS validation.

Each script follows consistent patterns for logging, error handling, and resource management while providing both automated workflows and manual control options. The scripts integrate with Kubernetes and Linkerd CLI tools to manage deployments, monitor traffic, and validate service mesh functionality. They support cleanup operations and provide detailed status information to help operators understand the current state of their canary deployments and service mesh configuration.
<!-- docgen:end id=apps/mesh-test-app/scripts:overview -->

<!-- docgen:begin id=apps/mesh-test-app/scripts:reference scope=apps/mesh-test-app/scripts hash=bd8145acf6f0 -->
## Reference

### `canary-deploy.sh`

- **`log`** (function)
- **`success`** (function)
- **`error`** (function)
- **`warn`** (function)
- **`build_v2`** (function): Build v2 of the application with visible changes
- **`deploy_canary`** (function): Deploy canary (v2) alongside stable (v1)
- **`monitor_traffic`** (function): Monitor traffic distribution
- **`test_traffic`** (function): Test traffic distribution
- **`promote_canary`** (function): Promote canary to stable (100% traffic)
- **`rollback_canary`** (function): Rollback canary deployment
- **`update_weights`** (function): Update traffic weights
- **`show_help`** (function): Show help
- **`show_status`** (function): Show status
- **`cleanup`** (function): Cleanup all canary resources
- **`trap_cleanup`** (function): Handle cleanup on script exit

### `linkerd-canary.sh`

- **`log`** (function)
- **`success`** (function)
- **`error`** (function)
- **`warn`** (function)
- **`init_linkerd_canary`** (function): Initialize Linkerd native canary deployment
- **`deploy_httproute_canary`** (function): Deploy HTTPRoute-based canary
- **`deploy_header_canary`** (function): Header-based canary for safe testing
- **`monitor_linkerd_traffic`** (function): Monitor Linkerd traffic stats
- **`analyze_live_traffic`** (function): Real-time traffic analysis
- **`check_mesh_health`** (function): Check Linkerd mesh health
- **`progressive_canary`** (function): Progressive canary deployment using Linkerd
- **`automated_canary`** (function): Automated canary with health monitoring
- **`cleanup_linkerd`** (function): Cleanup Linkerd resources
- **`show_help`** (function): Show help

### `setup-service-mesh.sh`

- **`log`** (function)
- **`success`** (function)
- **`error`** (function)
- **`warn`** (function)
- **`check_linkerd_cli`** (function): Check if Linkerd CLI is installed
- **`install_gateway_api`** (function): Install Gateway API CRDs (required for Linkerd)
- **`install_linkerd`** (function): Install Linkerd
- **`install_linkerd_viz`** (function): Install Linkerd Viz extension for observability
- **`install_trafficsplit_crd`** (function): Install TrafficSplit CRDs manually (since linkerd smi command may not exist)
- **`deploy_app`** (function): Build and deploy the test application
- **`test_setup`** (function): Test the setup
- **`show_access_info`** (function): Show access information
- **`main`** (function): Main execution
- **`cleanup`** (function): Handle cleanup on script exit

### `test-suite.sh`

- **`log`** (function)
- **`success`** (function)
- **`error`** (function)
- **`warn`** (function)
- **`info`** (function)
- **`cleanup`** (function): Cleanup function
- **`start_port_forward`** (function): Start port-forward
- **`generate_load`** (function): Generate load using curl
- **`monitor_metrics`** (function): Monitor service metrics during test
- **`test_zero_downtime`** (function): Test zero-downtime deployment
- **`test_mtls`** (function): Test service mesh mTLS
- **`test_health_during_deployment`** (function): Test application health during deployment
- **`analyze_results`** (function): Analyze test results
- **`run_test_suite`** (function): Run comprehensive test suite
- **`show_help`** (function): Show help
<!-- docgen:end id=apps/mesh-test-app/scripts:reference -->
