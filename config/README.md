# Dev Lab Configuration Externalization

This directory contains externalized configuration files that were previously embedded inline within the deployment scripts. This improves maintainability, readability, and allows for better version control of configuration changes.

## Directory Structure

```text
config/
├── apps/
│   └── sample-web-app.yaml          # Sample application manifests
├── gitops/
│   └── git-repository.yaml         # Flux GitRepository configuration
├── monitoring/
│   └── prometheus-values.yaml      # Prometheus stack Helm values
└── registry/
    ├── registry-daemonset.yaml     # Container registry DaemonSet
    └── registry-ui.yaml            # Container registry UI deployment
```

## Comparison with Original Notes Files

### Files Used from Notes Directory

The following files from `notes/dev-lab/` were determined to be better and were copied or used as reference:

1. **cluster/kind-config.yaml** - More comprehensive cluster configuration with:
   - Better networking setup
   - Proper port mappings for services
   - ContainerD configuration for local registry
   - Multi-node setup with proper labels

### Files Externalized from Scripts

The following configurations were extracted from inline script definitions:

1. **monitoring/prometheus-values.yaml**
   - **Source**: Inline YAML in `deploy-traditional.sh`
   - **Improvements**: Can now be version controlled and modified independently
   - **Comparison**: The notes version at `monitoring/prometheus-values-lightweight.yaml` was simpler but missing some Linkerd integrations, so we kept the script version which has better Linkerd metrics collection

1. **registry/registry-daemonset.yaml** & **registry-ui.yaml**
   - **Source**: Inline YAML in `bootstrap.sh`
   - **Improvements**: Separated registry and UI into different files for better modularity
   - **Comparison**: The notes version at `registry/registry-k8s-daemonset.yaml` was more comprehensive with:
     - Better health checks
     - More robust configuration
     - Proper tolerations and node selectors
     - However, it used `hostNetwork: true` which might conflict with the scripts' approach

1. **apps/sample-web-app.yaml**
   - **Source**: Inline YAML in `deploy-traditional.sh`
   - **Improvements**: Can be easily replaced with more complex applications
   - **Comparison**: The notes version at `apps/mesh-test-app/k8s/base.yaml` is much more sophisticated with:
     - Custom application instead of nginx
     - Better resource management
     - Proper health checks
     - Integration with Redis
     - More realistic service mesh testing capabilities

1. **gitops/git-repository.yaml**
   - **Source**: Inline YAML in `deploy-gitops.sh`
   - **Improvements**: Repository URL is parameterized via script substitution

## Recommendations for Further Improvement

### Consider Using Notes Directory Files

The files in `notes/dev-lab/` appear to be more mature and feature-complete:

1. **Registry Configuration**:
   - Consider using `notes/dev-lab/registry/registry-k8s-daemonset.yaml`
   - It has better health checks and more robust configuration
   - May need to adjust the networking approach to match script expectations

1. **Sample Application**:
   - The `notes/dev-lab/apps/mesh-test-app/` contains a full Node.js application
   - Much better for testing service mesh capabilities
   - Includes traffic splitting, canary deployments, and monitoring

1. **Monitoring Configuration**:
   - Compare `notes/dev-lab/monitoring/prometheus-values-lightweight.yaml`
   - May have better resource optimization for local development

### Benefits of Externalization

1. **Maintainability**: Configuration changes don't require script modification
2. **Version Control**: Better tracking of configuration changes
3. **Reusability**: Configurations can be used by other tools or scripts
4. **Testing**: Configurations can be validated independently
5. **Documentation**: Each file can have its own documentation and comments

### Script Changes Made

The following scripts were updated to use external files:

1. **bootstrap.sh**:
   - Registry configuration now loaded from `config/registry/`
   - Uses better kind-config.yaml from cluster directory

1. **deploy-traditional.sh**:
   - Monitoring values loaded from `config/monitoring/prometheus-values.yaml`
   - Sample app loaded from `config/apps/sample-web-app.yaml`

1. **deploy-gitops.sh**:
   - GitRepository config loaded from `config/gitops/git-repository.yaml`
   - Repository URL still parameterized via sed substitution

## Migration Notes

- All scripts maintain backward compatibility
- Configuration files are referenced using `$PROJECT_ROOT` relative paths
- Original inline configurations were preserved in the external files
- The notes directory files could replace these with minor adjustments if desired
