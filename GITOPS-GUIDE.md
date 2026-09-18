# DevLab GitOps Deployment Guide

This guide covers using the GitOps deployment method with Flux CD for automated infrastructure and application management.

## Overview

The GitOps deployment method uses Flux CD to automatically deploy and manage your infrastructure and applications from a Git repository. This provides:

- **Declarative Configuration**: Infrastructure as Code stored in Git
- **Automatic Deployment**: Changes to Git trigger deployments
- **Drift Detection**: Flux ensures cluster state matches Git
- **Rollback Capability**: Git history provides easy rollbacks
- **Security**: Read-only deploy keys, no cluster credentials needed

## Prerequisites

1. **Git Repository Access**: You need access to a Git repository (GitHub, GitLab, etc.)
2. **SSH Deploy Key**: The script will generate SSH keys for secure Git access
3. **Docker**: All tools run in containers

## Quick Start

```bash
# 1. Bootstrap the cluster (if not already done)
./devlab bootstrap

# 2. Deploy using GitOps
./devlab deploy-gitops
```

## Deployment Process

The GitOps deployment follows these steps:

### 1. Flux Controller Installation

- Installs Flux CD controllers in the `flux-system` namespace
- Sets up source controller, kustomize controller, and helm controller

### 2. SSH Key Generation

- Generates a new SSH key pair for secure Git access
- Creates a Kubernetes secret with the private key
- Displays the public key for adding to your Git repository

### 3. Git Repository Configuration

- Creates a GitRepository resource pointing to your Git repo
- Configures authentication using the SSH deploy key
- Sets up automatic syncing every 5 minutes

### 4. Kustomization Deployment

- Applies infrastructure kustomizations (NGINX, Prometheus, etc.)
- Applies application kustomizations (sample apps, etc.)
- Flux monitors and reconciles these automatically

## Repository Structure

Your Git repository should follow this structure:

```
your-repo/
├── dev-lab/
│   ├── infrastructure/
│   │   ├── kustomization.yaml
│   │   ├── nginx/
│   │   ├── monitoring/
│   │   └── registry/
│   └── apps/
│       ├── kustomization.yaml
│       └── sample-app/
└── clusters/
    └── dev-lab/
        └── dev-lab-kustomizations.yaml
```

## Configuration Files

### GitRepository Resource

Located at `config/gitops/git-repository.yaml`:

- Defines the Git repository source
- Configures SSH authentication
- Sets sync interval

### Kustomizations

Located at `clusters/dev-lab/dev-lab-kustomizations.yaml`:

- Defines what paths to deploy from Git
- Sets up dependencies between infrastructure and apps
- Configures health checks

## Monitoring GitOps

After deployment, monitor the GitOps system:

```bash
# Check all Flux resources
./devlab flux -- get all -A

# Watch kustomization status
watch ./devlab flux -- get kustomizations -A

# View controller logs
./devlab flux -- logs --all-namespaces

# Check for events
./devlab kubectl -- get events -n flux-system
```

## Common Operations

### Force Reconciliation

```bash
# Force sync of a specific kustomization
./devlab flux -- reconcile kustomization dev-lab-infrastructure -n flux-system

# Force sync of Git repository
./devlab flux -- reconcile source git dev-lab-repo -n flux-system
```

### Suspend/Resume

```bash
# Suspend automatic reconciliation
./devlab flux -- suspend kustomization dev-lab-apps -n flux-system

# Resume automatic reconciliation
./devlab flux -- resume kustomization dev-lab-apps -n flux-system
```

### Update Git Repository

```bash
# Update to a different branch
./devlab kubectl -- patch gitrepository dev-lab-repo -n flux-system --type='merge' -p='{"spec":{"ref":{"branch":"feature-branch"}}}'
```

## Security Considerations

1. **Deploy Keys**: Use read-only deploy keys for production
2. **Branch Protection**: Protect your main branch with required reviews
3. **Secret Management**: Flux handles sensitive data through sealed secrets or external secret operators
4. **Network Policies**: Consider implementing network policies to restrict pod communication

## Troubleshooting

### SSH Key Issues

```bash
# Check if secret exists
./devlab kubectl -- get secret dev-lab-repo -n flux-system

# Verify SSH key format
./devlab kubectl -- get secret dev-lab-repo -n flux-system -o yaml
```

### Repository Sync Issues

```bash
# Check GitRepository status
./devlab kubectl -- describe gitrepository dev-lab-repo -n flux-system

# Check for authentication errors
./devlab kubectl -- get events -n flux-system --field-selector reason=FailedSync
```

### Kustomization Failures

```bash
# Check kustomization status
./devlab kubectl -- describe kustomization dev-lab-infrastructure -n flux-system

# View detailed error messages
./devlab flux -- logs --level=error
```

## Advanced Configuration

### Multi-Environment Setup

For multiple environments (dev, staging, prod), use separate:

- Git branches or repositories
- Cluster directories
- Kustomization overlays

### Custom Flux Configuration

Modify the Flux installation by creating a `flux-config.yaml` file and using:

```bash
./devlab flux -- install --export > flux-config.yaml
# Edit the file, then apply
./devlab kubectl -- apply -f flux-config.yaml
```

### Notification Setup

Configure Flux to send notifications to Slack, Discord, or other systems:

```bash
# Example: Create notification provider
./devlab flux -- create alert-provider slack --type slack --webhook-url <webhook-url>

# Create alert for specific resources
./devlab flux -- create alert dev-lab-alert --provider-ref slack --event-severity info --event-source GitRepository/*
```

## Migration from Traditional Deployment

If you previously used traditional deployment:

1. **Export Current State**: Use `kubectl get` to export current configurations
2. **Create Git Repository**: Structure your configurations in Git
3. **Deploy GitOps**: Run `./devlab deploy-gitops`
4. **Verify Sync**: Ensure Flux recognizes existing resources
5. **Remove Manual Resources**: Clean up manually deployed resources

## Best Practices

1. **Small, Frequent Commits**: Make atomic changes to reduce risk
2. **Use Overlays**: Leverage Kustomize overlays for environment differences
3. **Health Checks**: Configure appropriate health checks for applications
4. **Documentation**: Keep deployment documentation in the same repository
5. **Backup**: Regular backups of both cluster state and Git repository
6. **Testing**: Test changes in development clusters before production

## Resources

- [Flux CD Documentation](https://fluxcd.io/docs/)
- [GitOps Principles](https://www.gitops.tech/)
- [Kustomize Documentation](https://kustomize.io/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
