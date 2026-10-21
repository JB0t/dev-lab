# Docker-in-Docker with the NVIDIA Container Toolkit, for scripts/cluster-registry.sh build
# with REG_BUILD_GPU: the inner dockerd runs containers with the nvidia runtime by default,
# so RUN steps of the legacy builder (DOCKER_BUILDKIT=0 docker build) see the pod's GPU.
# BuildKit (docker buildx build) runs RUN steps with plain runc and never gets a GPU.
# Build it anywhere (no GPU needed) and push it into the cluster registry:
#   docker build -t gpu-builder:1 config/cluster-registry/gpu-builder
#   scripts/cluster-registry.sh push gpu-builder:1
#   REG_BUILD_IMAGE=localhost:5000/gpu-builder:1 REG_BUILD_GPU=1 scripts/cluster-registry.sh build ...
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg iptables \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list \
    && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /etc/apt/keyrings/nvidia-container-toolkit.gpg \
    && curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
       | sed 's#deb https://#deb [signed-by=/etc/apt/keyrings/nvidia-container-toolkit.gpg] https://#' > /etc/apt/sources.list.d/nvidia-container-toolkit.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin nvidia-container-toolkit \
    && rm -rf /var/lib/apt/lists/* \
    # The nvidia runtime as the inner daemon's default; no cgroup device rules, as we run nested
    && nvidia-ctk runtime configure --runtime=docker --set-as-default \
    && sed -i 's/^#no-cgroups = false/no-cgroups = true/' /etc/nvidia-container-runtime/config.toml
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
VOLUME /var/lib/docker
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
