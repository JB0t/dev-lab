#!/usr/bin/env bash
# Build the GPU builder image with the repo's trusted CA certificates (python/certs) inside.
#   config/cluster-registry/gpu-builder/build.sh [TAG] [docker build args...]    (TAG defaults to gpu-builder:1)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
tag="${1:-gpu-builder:1}"; shift || true
# The certs/ directory is the only thing the Dockerfile can COPY; refresh it from python/certs
find "$here/certs" -type f -name '*.crt' -delete
if [ -d "$root/python/certs" ]; then
    find "$root/python/certs" -type f -name '*.crt' -exec cp {} "$here/certs/" \;
fi
count="$(find "$here/certs" -type f -name '*.crt' | wc -l | tr -d ' ')"
echo "Building $tag with $count trusted CA certificate(s) from python/certs"
exec docker build -t "$tag" "$@" "$here"
