# Migration Guide: Bash → Python Dev Lab

## Overview

This guide helps you migrate from the bash-based dev-lab scripts to the new Python-based platform-agnostic solution.

## Quick Migration

### 1. Test the Python Version

```bash
cd dev-lab/python
python3 setup.py
./devlab bootstrap
```

### 2. Compare Functionality

| Bash Script | Python Command | Notes |
|-------------|----------------|--------|
| `./scripts/install-prerequisites.sh` | Not needed | Only Docker required |
| `./scripts/bootstrap.sh` + `./scripts/deploy-traditional.sh` | `./devlab bootstrap` | Bootstrap also installs the registry, Traefik ingress, and monitoring |
| `./scripts/deploy-gitops.sh` | `./devlab deploy-gitops` | Optional |
| `kubectl ...` | `./devlab kubectl ...` | Container-based |
| `helm ...` | `./devlab helm ...` | Container-based |
| `linkerd ...` | `./devlab linkerd ...` | Container-based |

### 3. Key Differences

**Bash Version Requirements:**

- kubectl, helm, kind, linkerd CLI tools
- Platform-specific installation
- Linux/macOS only

**Python Version Requirements:**

- Only Docker
- Platform-agnostic
- Works on Windows, macOS, Linux

## Benefits Gained

1. **Platform Independence**: Works everywhere Docker runs
2. **Simplified Setup**: No tool installation required
3. **Consistent Versions**: Container-based tools ensure reproducibility
4. **Better UX**: Rich terminal output, progress bars, error handling
5. **Maintainability**: Clean Python code vs complex bash

## Test Your Migration

```bash
# Old way (if tools installed)
./scripts/bootstrap.sh
./scripts/deploy-traditional.sh

# New way (only Docker needed)
cd python
./devlab bootstrap
```

The Python version uses the Traefik ingress instead of NGINX and does not
deploy a sample app, so the clusters are not identical. See
[NETWORKING.md](../NETWORKING.md) for how services are exposed.

## Rollback Plan

The original bash scripts remain unchanged in the `scripts/` directory, so you can always fall back if needed.

## Next Steps

Once comfortable with the Python version:

1. Update documentation to reference Python commands
2. Consider deprecating bash scripts
3. Train team on new workflow
4. Enjoy platform-agnostic development! 
