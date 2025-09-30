# DevLab Container Tools Architecture

## Overview

DevLab uses a hybrid approach for tool execution that prioritizes performance while maintaining platform independence.

## Tool Execution Strategy

### 1. Host Binary First (Performance)

- **Check host system** for installed tools (kubectl, helm, linkerd, kind, flux)
- **Use directly** if found - fastest execution, no container overhead
- **Native performance** for users who have tools installed

### 2. Container Fallback (Platform Agnostic)

- **Pre-built local images** for tools when host binaries not available
- **One-time setup** - images built locally and cached
- **No network dependency** during runtime after initial build
- **Consistent versions** across all platforms

## Tool-Specific Implementation

### KinD (Kubernetes in Docker)

- **Challenge**: No official KinD CLI container image exists
- **Solution**: Local Dockerfile builds Alpine + KinD binary
- **Image**: `devlab-kind:latest` (~20MB)
- **Mount**: Docker socket for container management

### Other Tools (kubectl, helm, linkerd, flux)

- **Use official container images** from respective projects
- **Always containerized** for consistency
- **Volume mounts** for kubeconfig and workspace access

## Container Image Management

### Building Tool Images

```bash
# Build all local tool container images
./devlab build-tools

# This creates:
# - devlab-kind:latest (Alpine + KinD CLI)
```

### Image Caching

- **Docker layer caching** speeds up rebuilds
- **Small base images** (Alpine) minimize storage
- **Persistent storage** - images survive container restarts

## Performance Comparison

| Method | Speed | Setup | Platform Support |
|--------|-------|--------|------------------|
| Host Binary | ⚡ Fastest | ❌ Manual install | ⚠️ Platform specific |
| Pre-built Container | 🚀 Fast | ✅ Auto-build | ✅ Universal |
| Ephemeral Download | 🐌 Slow | ✅ No setup | ✅ Universal |

## Benefits of This Approach

### 1. **Best Performance**

- Host binaries used when available (zero overhead)
- Pre-built containers avoid download delays
- Minimal container startup time

### 2. **Platform Independence**

- Works on Windows, macOS, Linux
- Only Docker dependency required
- Automatic fallback handling

### 3. **Developer Experience**

- Transparent - users don't need to know which method is used
- Consistent behavior across environments
- No manual tool installation required

### 4. **Robustness**

- No network dependency during normal operation
- Graceful fallback when host tools unavailable
- Cached images survive system restarts

## Architecture Diagram

```
┌─────────────────┐    ┌──────────────────┐    ┌────────────────────┐
│   User Command  │───▶│  Tool Detection  │───▶│   Execution Path   │
└─────────────────┘    └──────────────────┘    └────────────────────┘
                                │                         │
                                ▼                         ▼
                       ┌─────────────────┐       ┌──────────────────┐
                       │ Host Binary?    │──YES─▶│ Direct Execution │
                       └─────────────────┘       └──────────────────┘
                                │                         │
                                NO                       ⚡ FASTEST
                                ▼                         
                       ┌─────────────────┐       ┌──────────────────┐
                       │ Local Image?    │──YES─▶│ Container Exec   │
                       └─────────────────┘       └──────────────────┘
                                │                         │
                                NO                       🚀 FAST
                                ▼                         
                       ┌─────────────────┐       ┌──────────────────┐
                       │ Build Image     │──────▶│ Container Exec   │
                       └─────────────────┘       └──────────────────┘
                                                          │
                                                       ✅ RELIABLE
```

## Maintenance

### Updating Tool Versions

1. Update `TOOL_VERSIONS` in `devlab.py`
2. Run `./devlab build-tools` to rebuild images
3. Test with `./devlab <tool> -- version`

### Troubleshooting

```bash
# Check if images exist
docker images | grep devlab

# Rebuild if needed
./devlab build-tools

# Test specific tool
docker run --rm devlab-kind:latest version
```

This architecture provides the optimal balance of performance, reliability, and platform independence for the DevLab development environment.
