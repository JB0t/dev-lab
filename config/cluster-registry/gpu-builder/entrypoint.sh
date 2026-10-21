#!/bin/sh
# Start the inner dockerd (plain socket, no TLS); extra arguments go to it, e.g. --insecure-registry=HOST
set -e
mkdir -p /var/run
# A privileged pod on a GPU node sees /dev/nvidia* whether or not it was given a GPU; what
# tells them apart is the driver the node's runtime injects with the GPU (nvidia-smi works)
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    # The pod has a GPU: containers run with the nvidia runtime (set as default at build time), so
    # RUN steps of the legacy builder see it
    echo 'export DOCKER_BUILDKIT=0' > /etc/profile.d/legacy-builder.sh
    echo "GPU present: the nvidia runtime is the default; use DOCKER_BUILDKIT=0 docker build for RUN steps that need it"
    exec dockerd --host=unix:///var/run/docker.sock "$@"
fi
# No GPU on this pod (REG_BUILD_GPU=0): plain runc, or the nvidia hook would refuse to start any
# container whose image sets NVIDIA_VISIBLE_DEVICES
# (daemon.json sets the default runtime, and dockerd refuses the same setting as a flag)
echo "No GPU device: containers run with runc"
sed -i '/"default-runtime"/d' /etc/docker/daemon.json
exec dockerd --host=unix:///var/run/docker.sock "$@"
