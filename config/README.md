# Dev Lab Configuration Externalization

This directory contains externalized configuration files that were previously embedded inline within the deployment scripts. This improves maintainability, readability, and allows for better version control of configuration changes.

## Directory Structure

```text
config/
├── gitops/
│   ├── git-repository.yaml         # Flux GitRepository configuration
│   └── service-mesh-layer-gitrepository.yaml
├── ingress/
│   └── traefik-values.yaml         # Traefik ingress controller Helm values
├── monitoring/
│   └── prometheus-values.yaml      # Prometheus stack Helm values
└── registry/
    ├── registry.yaml               # Container registry Deployment
    └── registry-ui.yaml            # Container registry UI deployment
```

## Comparison with Original Notes Files

### Files Used from Notes Directory

The following files from `notes/dev-lab/` were determined to be better and were copied or used as reference:

1. **cluster/kind-config.yaml** - More comprehensive cluster configuration with:
   - Better networking setup
   - Host port mappings for the registry (5000) and the Traefik ingress (80/443)
   - ContainerD configuration for local registry
   - Multi-node setup (1 control-plane + 2 workers)

### Files Externalized from Scripts

The following configurations were extracted from inline script definitions:

1. **monitoring/prometheus-values.yaml**
   - **Source**: Inline YAML in `deploy-traditional.sh`
   - **Improvements**: Can now be version controlled and modified independently
   - **Comparison**: The notes version at `monitoring/prometheus-values-lightweight.yaml` was simpler but missing some Linkerd integrations, so we kept the script version which has better Linkerd metrics collection

1. **registry/registry.yaml** & **registry-ui.yaml**
   - **Source**: Inline YAML in `bootstrap.sh`
   - **Improvements**: Separated registry and UI into different files for better modularity
   - **Current state**: The registry is a single Deployment pinned to the control-plane node. Its storage persists in `/tmp/dev-lab-registry` on the Docker host. The UI is served at <http://registry.localhost> through the Traefik ingress.

1. **ingress/traefik-values.yaml**
   - Helm values for the Traefik ingress controller (chart `traefik/traefik`), installed by `devlab bootstrap`
   - See [NETWORKING.md](../NETWORKING.md) for how ingress and port mappings work

1. **gitops/git-repository.yaml**
   - **Source**: Inline YAML in `deploy-gitops.sh`
   - **Improvements**: Repository URL is parameterized via script substitution

## Recommendations for Further Improvement

### Consider Using Notes Directory Files

The files in `notes/dev-lab/` appear to be more mature and feature-complete:

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

1. **deploy-gitops.sh**:
   - GitRepository config loaded from `config/gitops/git-repository.yaml`
   - Repository URL still parameterized via sed substitution

## Migration Notes

- All scripts maintain backward compatibility
- Configuration files are referenced using `$PROJECT_ROOT` relative paths
- Original inline configurations were preserved in the external files
- The notes directory files could replace these with minor adjustments if desired
