# Build the Dask GPU image inside a cluster (CLUSTER-REGISTRY-RUNBOOK.md, "Build in the cluster"):
#   scripts/cluster-registry.sh build config/dask/image
# Runs in this directory on the build pod. $REG is the registry's in-cluster address;
# pods pull the result as localhost:5000/devlab-dask-gpu:2026.1.1 ($REG_PULL/...).
docker buildx build -t "$REG/devlab-dask-gpu:2026.1.1" --push .
