#!/bin/bash

# Configure containerd for insecure registry access on all nodes
echo "Configuring containerd for insecure registry access..."

# Function to configure containerd on a node
configure_node() {
    local node_name=$1
    echo "Configuring $node_name..."
    
    docker exec "$node_name" tee /etc/containerd/config.toml > /dev/null << 'EOF'
version = 2

[plugins]
  [plugins."io.containerd.grpc.v1.cri"]
    restrict_oom_score_adj = false
    sandbox_image = "registry.k8s.io/pause:3.7"
    tolerate_missing_hugepages_controller = true
    [plugins."io.containerd.grpc.v1.cri".containerd]
      default_runtime_name = "runc"
      discard_unpacked_layers = true
      snapshotter = "overlayfs"
      [plugins."io.containerd.grpc.v1.cri".containerd.runtimes]
        [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
          base_runtime_spec = "/etc/containerd/cri-base.json"
          runtime_type = "io.containerd.runc.v2"
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
            SystemdCgroup = true
        [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.test-handler]
          base_runtime_spec = "/etc/containerd/cri-base.json"
          runtime_type = "io.containerd.runc.v2"
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.test-handler.options]
            SystemdCgroup = true
    [plugins."io.containerd.grpc.v1.cri".registry]
      [plugins."io.containerd.grpc.v1.cri".registry.configs]
        [plugins."io.containerd.grpc.v1.cri".registry.configs."dev-lab-control-plane:5000"]
          [plugins."io.containerd.grpc.v1.cri".registry.configs."dev-lab-control-plane:5000".tls]
            insecure_skip_verify = true
          [plugins."io.containerd.grpc.v1.cri".registry.configs."dev-lab-control-plane:5000".plain_http]
            true
        [plugins."io.containerd.grpc.v1.cri".registry.configs."localhost:5000"]
          [plugins."io.containerd.grpc.v1.cri".registry.configs."localhost:5000".tls]
            insecure_skip_verify = true
          [plugins."io.containerd.grpc.v1.cri".registry.configs."localhost:5000".plain_http]
            true
      [plugins."io.containerd.grpc.v1.cri".registry.mirrors]
        [plugins."io.containerd.grpc.v1.cri".registry.mirrors."localhost:5000"]
          endpoint = ["http://dev-lab-control-plane:5000"]

[proxy_plugins]
  [proxy_plugins.fuse-overlayfs]
    address = "/run/containerd-fuse-overlayfs.sock"
    type = "snapshot"
EOF

    # Restart containerd
    docker exec "$node_name" systemctl restart containerd
    
    # Restart kubelet
    docker exec "$node_name" systemctl restart kubelet
}

# Configure all worker nodes
for node in dev-lab-worker dev-lab-worker2; do
    if docker ps --format "table {{.Names}}" | grep -q "^$node$"; then
        configure_node "$node"
    else
        echo "Node $node not found, skipping..."
    fi
done

echo "Registry configuration complete!"