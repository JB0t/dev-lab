# Dask GPU image for the dev-lab Dask clusters (DASK-GPU-RUNBOOK.md)
# Build into the local registry: ./devlab build -t devlab-dask-gpu:2026.1.1 --push config/dask/image
FROM python:3.12.12-slim-bookworm

# libgomp1: LightGBM's OpenMP runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -c /tmp/constraints.txt \
    && pip check

# The host driver is injected by the nvidia runtime; ask for compute + utility
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    # numba-cuda allocates from the worker's RMM pool, so it counts against the
    # worker's GPU memory limit
    NUMBA_CUDA_MEMORY_MANAGER=rmm.allocators.numba
