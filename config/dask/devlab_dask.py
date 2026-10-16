"""Dask clusters with time-sliced GPU workers on the dev-lab cluster.

Uses the Dask Kubernetes Operator (``devlab addon enable dask-operator``). The
client decides the cluster's shape; the scheduler then asks for workers as
tasks are submitted, from 0 up to ``n_workers``, and they are removed again
when idle::

    from dask.distributed import Client
    from devlab_dask import gpu_cluster

    with gpu_cluster("analysis", n_workers=4, gpu_memory_gib=5) as cluster, Client(cluster) as client:
        ...  # submit work; GPU workers start for it and stop when idle

GPU memory: each GPU node advertises one ``nvidia.com/gpu`` share per GiB of
GPU memory. A worker requests ``gpu_memory_gib`` shares, so Kubernetes only
starts it where that much GPU memory is free, on any GPU node. Workers of
different sizes can share a GPU. Time slicing does not isolate GPU memory:
with ``rmm_pool=True`` (default) the worker limits memory allocated through
RMM to a fixed pool of its size minus its CUDA context; libraries with their
own CUDA allocator (e.g. XGBoost) are not limited and should run with
``rmm_pool=False``, so the pool does not hold memory they cannot use.

Placement: workers tolerate the GPU node taint and run only on GPU nodes
(``devlab.io/gpu=true``); the scheduler runs on a CPU node
(``devlab.io/gpu=false``).
"""

import math
from typing import Dict, Optional

# One image for scheduler, workers and clients (config/dask/image), so all
# sides run the same Dask version. Built into the local registry with
#   ./devlab build -t devlab-dask-gpu:2026.1.1 --push config/dask/image
IMAGE = "localhost:5000/devlab-dask-gpu:2026.1.1"

# GPU memory a worker uses outside its RMM pool (CUDA context, libraries)
CUDA_CONTEXT_GIB = 0.5

SCHEDULER_PORT = 8786
DASHBOARD_PORT = 8787
WORKER_DASHBOARD_PORT = 8788

# The DaskAutoscaler reads /api/v1/adaptive_target, which is not in the
# scheduler's default HTTP routes
SCHEDULER_HTTP_ROUTES = [
    "distributed.http.scheduler.prometheus",
    "distributed.http.scheduler.info",
    "distributed.http.scheduler.json",
    "distributed.http.health",
    "distributed.http.proxy",
    "distributed.http.statics",
    "distributed.http.scheduler.api",
]

GPU_TOLERATION = {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}

# Namespace of the pod a client runs in
SERVICE_ACCOUNT_NAMESPACE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def gib(value: float) -> str:
    """Format a GiB amount for Dask, e.g. 4.5 -> '4.5GiB'."""
    return f"{value:g}GiB"


def worker_memory(gpu_memory_gib: int) -> Dict[str, str]:
    """RMM pool and spill threshold for a worker with ``gpu_memory_gib`` shares."""
    if gpu_memory_gib < 1:
        raise ValueError("gpu_memory_gib must be at least 1")
    pool = max(gpu_memory_gib - CUDA_CONTEXT_GIB, 0.5)
    # Spill Dask data to host memory before the pool is full
    spill = math.floor(pool * 0.9 * 4) / 4
    return {"pool": gib(pool), "spill": gib(spill)}


def gpu_cluster_spec(
    name: str,
    gpu_memory_gib: int,
    image: str = IMAGE,
    host_memory: str = "8Gi",
    task_durations: Optional[Dict[str, str]] = None,
    worker_resources: Optional[Dict[str, float]] = None,
    rmm_pool: bool = True,
) -> dict:
    """DaskCluster resource for GPU workers with ``gpu_memory_gib`` GiB of GPU memory each.

    ``task_durations`` tells the scheduler how long tasks of a given name
    (the function name) take, e.g. ``{"train": "2m"}``, so it asks for enough
    workers right away instead of starting with one. ``worker_resources``
    become Dask worker resources, e.g. ``{"GPU": 1}``, which tasks can require
    with ``client.submit(..., resources={"GPU": 1})``. ``rmm_pool`` gives
    the worker a fixed RMM pool of its GPU memory; turn it off for code that
    does not allocate through RMM.
    """
    memory = worker_memory(gpu_memory_gib)
    worker_args = [
        "dask", "cuda", "worker", "$(DASK_SCHEDULER_ADDRESS)",
        "--name", "$(DASK_WORKER_NAME)",
        "--nthreads", "1",
        "--device-memory-limit", memory["spill"],
        "--dashboard-address", f":{WORKER_DASHBOARD_PORT}",
    ]
    if rmm_pool:
        worker_args += ["--rmm-pool-size", memory["pool"], "--rmm-maximum-pool-size", memory["pool"]]
    if worker_resources:
        worker_args += ["--resources", " ".join(f"{key}={value}" for key, value in worker_resources.items())]

    scheduler_env = [{"name": "DASK_DISTRIBUTED__SCHEDULER__HTTP__ROUTES", "value": repr(SCHEDULER_HTTP_ROUTES)}]
    if task_durations:
        scheduler_env.append({
            "name": "DASK_DISTRIBUTED__SCHEDULER__DEFAULT_TASK_DURATIONS",
            "value": repr(dict(task_durations)),
        })

    labels = {"dask.org/cluster-name": name, "dask.org/component": "scheduler"}
    return {
        "apiVersion": "kubernetes.dask.org/v1",
        "kind": "DaskCluster",
        "metadata": {"name": name},
        "spec": {
            "worker": {
                # The DaskAutoscaler sets this; workers start when tasks arrive
                "replicas": 0,
                "spec": {
                    "runtimeClassName": "nvidia",
                    "nodeSelector": {"devlab.io/gpu": "true"},
                    "tolerations": [GPU_TOLERATION],
                    "containers": [{
                        "name": "worker",
                        "image": image,
                        "imagePullPolicy": "IfNotPresent",
                        "args": worker_args,
                        "ports": [{"name": "http-dashboard", "containerPort": WORKER_DASHBOARD_PORT, "protocol": "TCP"}],
                        "resources": {
                            "requests": {"cpu": "500m", "memory": "2Gi"},
                            "limits": {
                                # One share per GiB of GPU memory. The DaskCluster
                                # CRD only accepts quantities as strings
                                "nvidia.com/gpu": str(gpu_memory_gib),
                                "memory": host_memory,
                            },
                        },
                    }],
                },
            },
            "scheduler": {
                "spec": {
                    "nodeSelector": {"devlab.io/gpu": "false"},
                    "containers": [{
                        "name": "scheduler",
                        "image": image,
                        "imagePullPolicy": "IfNotPresent",
                        "args": ["dask", "scheduler", "--port", str(SCHEDULER_PORT),
                                 "--dashboard-address", f":{DASHBOARD_PORT}"],
                        "env": scheduler_env,
                        "ports": [
                            {"name": "tcp-comm", "containerPort": SCHEDULER_PORT, "protocol": "TCP"},
                            {"name": "http-dashboard", "containerPort": DASHBOARD_PORT, "protocol": "TCP"},
                        ],
                        "readinessProbe": {"httpGet": {"port": "http-dashboard", "path": "/health"},
                                           "initialDelaySeconds": 5, "periodSeconds": 5},
                        "livenessProbe": {"httpGet": {"port": "http-dashboard", "path": "/health"},
                                          "initialDelaySeconds": 15, "periodSeconds": 20},
                        "resources": {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"memory": "2Gi"}},
                    }],
                },
                "service": {
                    "type": "ClusterIP",
                    "selector": labels,
                    "ports": [
                        {"name": "tcp-comm", "protocol": "TCP", "port": SCHEDULER_PORT, "targetPort": "tcp-comm"},
                        {"name": "http-dashboard", "protocol": "TCP", "port": DASHBOARD_PORT,
                         "targetPort": "http-dashboard"},
                    ],
                },
            },
        },
    }


def default_namespace(service_account_namespace: str = SERVICE_ACCOUNT_NAMESPACE) -> Optional[str]:
    """Namespace for clusters when the caller gives none.

    In a pod: the pod's namespace. kr8s (used by dask-kubernetes) does not read
    it and falls back to "default". Elsewhere: None, so the kubeconfig's
    current namespace is used.
    """
    import dask

    configured = dask.config.get("kubernetes.namespace", default=None)
    if configured:
        return configured
    try:
        with open(service_account_namespace) as f:
            return f.read().strip() or None
    except OSError:
        return None


def gpu_cluster(name: str, n_workers: int, gpu_memory_gib: int, namespace: Optional[str] = None, **spec_options):
    """Create a Dask cluster whose GPU workers scale between 0 and ``n_workers``.

    Returns a ``dask_kubernetes.operator.KubeCluster``; the cluster is deleted
    when it is closed. ``namespace`` defaults to the client pod's namespace in
    the cluster, or the kubeconfig's current namespace outside it. See
    ``gpu_cluster_spec`` for ``spec_options``.
    """
    from dask_kubernetes.operator import KubeCluster

    cluster = KubeCluster(
        custom_cluster_spec=gpu_cluster_spec(name, gpu_memory_gib, **spec_options),
        namespace=namespace or default_namespace(),
        shutdown_on_close=True,
    )
    cluster.adapt(minimum=0, maximum=n_workers)
    return cluster
