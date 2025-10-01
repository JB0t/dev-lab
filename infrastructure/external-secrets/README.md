# External Secrets Management

This directory contains the configuration for deploying and managing secrets using the External Secrets Operator (ESO).

## Overview

The External Secrets Operator allows you to fetch secrets from external secrets managers (e.g., Doppler, AWS Secrets Manager, HashiCorp Vault, GitHub Actions Secrets) and store them as Kubernetes Secrets. This enables you to keep your sensitive data out of your Git repository and manage it centrally in a dedicated secrets manager.

## Dev Lab Implementation

This implementation specifically includes:

### Linkerd Trust Anchor Integration

The External Secrets Operator has been integrated to securely manage Linkerd trust anchor certificates using GitHub Actions Secrets as the secret store. This replaces the previous static certificate files with a dynamic, externally-managed approach.

#### Architecture

```
┌─────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────┐
│   GitHub Secrets   │    │  External Secrets      │    │   Service Mesh      │
│                     │    │  Operator               │    │   (Linkerd)         │
│  - LINKERD_TRUST_   │◄───┤                         │◄───┤                     │
│    ANCHOR_CERT      │    │  - ClusterSecretStore   │    │  - ExternalSecret   │
│  - LINKERD_TRUST_   │    │  - GitHub Auth          │    │  - linkerd-trust-   │
│    ANCHOR_KEY       │    │                         │    │    anchor secret    │
└─────────────────────┘    └─────────────────────────┘    └─────────────────────┘
```

#### Components in This Directory

**Purpose**: Provides the External Secrets Operator and dev-lab-specific GitHub integration.

**Resources**:
- `external-secrets` Helm operator installation
- `github-secret-store` (namespace-scoped) 
- `github-cluster-secret-store` (cluster-scoped for cross-namespace access to service-mesh)
- GitHub authentication secret template

**Dependencies**: 
- Depends on: `dev-lab-base`
- Required by: `dev-lab-service-mesh` (which contains the actual ExternalSecret for Linkerd)

#### Secret Management Flow

1. **Certificate Generation**: Use `scripts/generate-linkerd-trust-anchor.sh` to generate new trust anchor certificates
2. **GitHub Secrets Storage**: Script automatically uploads certificates to GitHub Secrets:
   - `LINKERD_TRUST_ANCHOR_CERT`
   - `LINKERD_TRUST_ANCHOR_KEY`
3. **External Secrets Sync**: ESO pulls secrets from GitHub and creates Kubernetes secrets in the service-mesh namespace
4. **Linkerd Integration**: Service mesh uses the externally-managed `linkerd-trust-anchor` secret

#### Usage

1. **Generate and Upload Certificates**:
   ```bash
   ./scripts/generate-linkerd-trust-anchor.sh
   ```

2. **Configure GitHub Authentication**:
   ```bash
   # Create a GitHub Personal Access Token with 'repo' scope
   kubectl create secret generic github-auth-secret \
     --from-literal=token="ghp_your_token_here" \
     -n external-secrets
   ```

3. **The ExternalSecret is managed by the service-mesh component**, which references the ClusterSecretStore from this component.

#### Security Benefits

1. **No Static Secrets in Git**: Trust anchor certificates are no longer stored as static files
2. **Centralized Secret Management**: GitHub Secrets provides audit logs and access control
3. **Automatic Rotation**: ESO can detect and sync certificate updates automatically
4. **Namespace Isolation**: ClusterSecretStore allows controlled cross-namespace access

1. **GitHub Actions Secrets Integration**: For dev-lab testing and development
2. **Linkerd Trust Anchor Management**: Secure certificate management for service mesh
3. **Cross-namespace Secret Access**: Using ClusterSecretStore for linkerd namespace

## Components

* **HelmRepository:** Defines the Helm repository for the External Secrets Operator chart.
* **HelmRelease:** Deploys the External Secrets Operator.
* **ClusterSecretStore:** Configures GitHub as a secret provider with cross-namespace access.
* **ExternalSecret:** Syncs Linkerd trust anchor certificates from GitHub Actions Secrets.

## Linkerd Trust Anchor Integration

### Architecture

```
GitHub Actions Secrets → External Secrets Operator → Kubernetes Secret → Linkerd
```

The system replaces static certificate files with dynamic secret management:

- `LINKERD_TRUST_ANCHOR_CERT` (GitHub Secret) → `tls.crt` (Kubernetes Secret)
- `LINKERD_TRUST_ANCHOR_KEY` (GitHub Secret) → `tls.key` (Kubernetes Secret)

### Setup Instructions

1. **Generate and Upload Certificates**:
   ```bash
   ./scripts/generate-linkerd-trust-anchor.sh
   ```

2. **Configure GitHub Authentication**:
   ```bash
   kubectl create secret generic github-auth-secret \
     --from-literal=token="ghp_your_actual_token_here" \
     -n external-secrets
   ```

3. **Deploy Infrastructure**:
   ```bash
   ./scripts/deploy-gitops.sh
   ```

### Verification

```bash
# Check operator status
kubectl get pods -n external-secrets

# Check secret store
kubectl get clustersecretstore

# Check external secret
kubectl get externalsecret -n linkerd
kubectl describe externalsecret linkerd-trust-anchor-external -n linkerd

# Verify generated secret
kubectl get secret linkerd-trust-anchor -n linkerd
```

### Security Benefits

- No static certificate files in Git repository
- Centralized secret management in GitHub
- Automatic synchronization and rotation support
- Access control via GitHub repository permissions

### Production Migration

For production, replace GitHub provider with AWS Secrets Manager:

```yaml
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-west-2
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets-sa
```

See the full documentation in the README.md for detailed configuration and troubleshooting information.
* **HelmRelease:** Deploys the External Secrets Operator using the Helm chart.
* **Kustomization:** Deploys the `SecretStore` and `ExternalSecret` resources.
* **Namespace:** Defines the namespace where ESO will be deployed.

## Usage

1. **Configure your Secrets Manager:**
    - Create a project or store in your chosen secrets manager (e.g., Doppler).
    - Add your secrets to the secrets manager.

2. **Update the Configuration:**
    - **`helmrepository.yaml`:**  Ensure the `url` points to the correct Helm repository for ESO.
    - **`helmrelease.yaml`:**
        - Set the `namespace` to your desired namespace for ESO.
        - Configure any other desired HelmRelease settings (e.g., version, values).
    - **`kustomization.yaml`:**
        - Update the `path` to point to your `SecretStore` and `ExternalSecret` YAML files.
        - Set the `targetNamespace` to the namespace where you want to store the Kubernetes Secrets.
    - **`namespace.yaml`:**  Set the `name` to your desired namespace for ESO.


3. **Commit and Push:**
    - Commit your changes to the Git repository.
    - Flux will automatically deploy the External Secrets Operator and your secret configurations.

## Referencing Secrets in Applications

- In your application deployments, you can reference the secrets created by ESO using `secretKeyRef` or `envFrom`.

## Security Considerations

- **Doppler Service Token:** Use Sealed Secrets or SOPS to encrypt your Doppler service token and store it securely in Git.
- **Access Control:**  Use Kyverno policies or other access control mechanisms to restrict access to secrets at the application level.

## Troubleshooting

- **Logs:** Check the logs of the External Secrets Operator pods for any errors or warnings.
- **Status:** Use `kubectl get externalsecret` to check the status of your `ExternalSecret` resources.

## Contributing

- Feel free to contribute to this configuration by submitting pull requests or opening issues.