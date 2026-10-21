#!/bin/sh
# Start the inner dockerd (plain socket, no TLS); extra arguments go to it, e.g. --insecure-registry=HOST
set -e
mkdir -p /var/run
# The legacy builder is the one that honours the default runtime, so RUN steps get the GPU
echo 'export DOCKER_BUILDKIT=0' > /etc/profile.d/legacy-builder.sh
exec dockerd --host=unix:///var/run/docker.sock "$@"
