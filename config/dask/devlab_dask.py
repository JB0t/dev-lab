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

Standing cluster: for existing code that connects with
``Client("tcp://<scheduler>:8786")``, run this file to create a long-lived
cluster whose scheduler keeps a fixed address and whose GPU workers scale
from 0 for whatever its clients submit::

    python3 config/dask/devlab_dask.py gpu --workers 4 --gpu-memory-gib 5 \\
        | devlab kubectl apply -n dask -f -

    Client("tcp://<host IP>:8786")               # from other machines
    Client("tcp://localhost:8786")               # on the Docker host
    Client("tcp://dev-lab-control-plane:30786")  # in a container on the kind network
    Client("tcp://gpu-scheduler.dask:8786")      # in a pod
    # dashboard: http://<host IP>:8787/workers or http://gpu.dask.localhost/workers
"""

import argparse
import asyncio
import json
import math
import sys
import time
from typing import Dict, List, Optional

# One image for scheduler, workers and clients (config/dask/image), so all
# sides run the same Dask version. Built into the local registry with
#   ./devlab build -t devlab-dask-gpu:2026.1.1 --push config/dask/image
IMAGE = "localhost:5000/devlab-dask-gpu:2026.1.1"

# GPU memory a worker uses outside its RMM pool (CUDA context, libraries)
CUDA_CONTEXT_GIB = 0.5

# Dask worker resources every GPU worker declares unless told otherwise, so
# tasks submitted with resources={"GPU": 1} find a worker. Each worker runs one
# task at a time (--nthreads 1), so this limits nothing else.
DEFAULT_WORKER_RESOURCES = {"GPU": 1}

SCHEDULER_PORT = 8786
# NodePort of the standing cluster's scheduler; kind publishes it as port
# 8786 on every interface of the Docker host (cluster/kind-config.yaml)
STANDING_SCHEDULER_NODE_PORT = 30786
# NodePort of its dashboard, published as port 8787 of the Docker host
STANDING_DASHBOARD_NODE_PORT = 30787
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
    gpu_shares: Optional[int] = None,
    image: str = IMAGE,
    host_memory: str = "8Gi",
    task_durations: Optional[Dict[str, str]] = None,
    worker_resources: Optional[Dict[str, float]] = None,
    rmm_pool: bool = True,
    unknown_task_duration: Optional[str] = None,
    worker_env: Optional[List[dict]] = None,
    worker_env_from: Optional[List[dict]] = None,
    worker_volumes: Optional[List[dict]] = None,
    worker_volume_mounts: Optional[List[dict]] = None,
    idle_timeout: Optional[int] = None,
    scheduler_node_port: Optional[int] = None,
    dashboard_node_port: Optional[int] = None,
    worker_node_selector: Optional[Dict[str, str]] = None,
    worker_tolerations: Optional[List[dict]] = None,
    scheduler_node_selector: Optional[Dict[str, str]] = None,
    scheduler_tolerations: Optional[List[dict]] = None,
    runtime_class: Optional[str] = "nvidia",
    one_worker_per_node: bool = False,
    worker_cpu: str = "500m",
) -> dict:
    """DaskCluster resource for GPU workers with ``gpu_memory_gib`` GiB of GPU memory each.

    ``gpu_shares`` is how many ``nvidia.com/gpu`` the worker requests: with
    time slicing one per GiB, so it defaults to ``gpu_memory_gib``; with MPS
    (GPU.md) a share is a fixed slice of the GPU, so pass ``gpu_shares=1`` and
    the slice's memory as ``gpu_memory_gib``.
    ``task_durations`` tells the scheduler how long tasks of a given name
    (the function name) take, e.g. ``{"train": "2m"}``, so it asks for enough
    workers right away instead of starting with one. ``worker_resources``
    become Dask worker resources, which tasks can require with
    ``client.submit(..., resources={"GPU": 1})``; the default is
    ``DEFAULT_WORKER_RESOURCES`` (``{"GPU": 1}``) and ``{}`` declares none. ``rmm_pool`` gives
    the worker a fixed RMM pool of its GPU memory; turn it off for code that
    does not allocate through RMM. ``unknown_task_duration`` is how long the
    scheduler assumes any task without a known duration takes (Dask's default
    is 0.5s); e.g. "5m" makes it ask for one worker per queued task.
    ``worker_env``, ``worker_env_from``, ``worker_volumes`` and
    ``worker_volume_mounts`` are added to the worker pods (Kubernetes env,
    envFrom, volumes and volumeMounts), e.g. ``worker_env_from=[{"configMapRef":
    {"name": "worker-env"}}]`` for every key of a ConfigMap as a variable.
    ``idle_timeout`` (seconds) has the operator delete the cluster when its
    scheduler has been idle that long, e.g. after its client was killed.
    ``scheduler_node_port`` makes the scheduler Service a NodePort with this
    port for the scheduler (TCP 8786), reachable on every node, and
    ``dashboard_node_port`` the port for its dashboard (HTTP 8787).

    Placement, for clusters other than the lab's: ``worker_node_selector``
    (default ``devlab.io/gpu=true``) and ``worker_tolerations`` (default the
    ``nvidia.com/gpu`` taint) for the GPU pool, ``scheduler_node_selector``
    (default ``devlab.io/gpu=false``) and ``scheduler_tolerations`` for the
    CPU pool; ``runtime_class`` is the pods' RuntimeClass (``nvidia`` from
    the GPU Operator; None where the default runtime has the GPU hooks, as
    on AKS). ``one_worker_per_node`` adds a required anti-affinity between
    the cluster's workers, so each takes a node (one worker per GPU node);
    ``worker_cpu`` is the worker's CPU request.
    """
    memory = worker_memory(gpu_memory_gib)
    if gpu_shares is None:
        gpu_shares = gpu_memory_gib
    if gpu_shares < 1:
        raise ValueError("gpu_shares must be at least 1")
    worker_args = [
        "dask", "cuda", "worker", "$(DASK_SCHEDULER_ADDRESS)",
        "--name", "$(DASK_WORKER_NAME)",
        "--nthreads", "1",
        "--device-memory-limit", memory["spill"],
        "--dashboard-address", f":{WORKER_DASHBOARD_PORT}",
    ]
    if rmm_pool:
        worker_args += ["--rmm-pool-size", memory["pool"], "--rmm-maximum-pool-size", memory["pool"]]
    if worker_resources is None:
        worker_resources = DEFAULT_WORKER_RESOURCES
    if worker_resources:
        worker_args += ["--resources", " ".join(f"{key}={value:g}" for key, value in worker_resources.items())]

    scheduler_env = [{"name": "DASK_DISTRIBUTED__SCHEDULER__HTTP__ROUTES", "value": repr(SCHEDULER_HTTP_ROUTES)}]
    if task_durations:
        scheduler_env.append({
            "name": "DASK_DISTRIBUTED__SCHEDULER__DEFAULT_TASK_DURATIONS",
            "value": repr(dict(task_durations)),
        })
    if unknown_task_duration:
        scheduler_env.append({
            "name": "DASK_DISTRIBUTED__SCHEDULER__UNKNOWN_TASK_DURATION",
            "value": unknown_task_duration,
        })

    worker_container = {
        "name": "worker",
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "args": worker_args,
        "ports": [{"name": "http-dashboard", "containerPort": WORKER_DASHBOARD_PORT, "protocol": "TCP"}],
        "resources": {
            "requests": {"cpu": worker_cpu, "memory": "2Gi"},
            "limits": {
                # The DaskCluster CRD only accepts quantities as strings
                "nvidia.com/gpu": str(gpu_shares),
                "memory": host_memory,
            },
        },
    }
    if worker_env:
        worker_container["env"] = list(worker_env)
    if worker_env_from:
        worker_container["envFrom"] = list(worker_env_from)
    if worker_volume_mounts:
        worker_container["volumeMounts"] = list(worker_volume_mounts)
    worker_pod = {
        "nodeSelector": dict(worker_node_selector) if worker_node_selector is not None else {"devlab.io/gpu": "true"},
        "tolerations": list(worker_tolerations) if worker_tolerations is not None else [GPU_TOLERATION],
        "containers": [worker_container],
    }
    if runtime_class:
        worker_pod["runtimeClassName"] = runtime_class
    if one_worker_per_node:
        worker_pod["affinity"] = {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [{
            "labelSelector": {"matchLabels": {"dask.org/cluster-name": name, "dask.org/component": "worker"}},
            "topologyKey": "kubernetes.io/hostname",
        }]}}
    if worker_volumes:
        worker_pod["volumes"] = list(worker_volumes)
    scheduler_pod = {
        "nodeSelector": dict(scheduler_node_selector) if scheduler_node_selector is not None
        else {"devlab.io/gpu": "false"},
    }
    if scheduler_tolerations:
        scheduler_pod["tolerations"] = list(scheduler_tolerations)

    labels = {"dask.org/cluster-name": name, "dask.org/component": "scheduler"}
    spec = {
        "apiVersion": "kubernetes.dask.org/v1",
        "kind": "DaskCluster",
        "metadata": {"name": name},
        "spec": {
            "worker": {
                # The DaskAutoscaler sets this; workers start when tasks arrive
                "replicas": 0,
                "spec": worker_pod,
            },
            "scheduler": {
                "spec": {
                    **scheduler_pod,
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
                    "type": "NodePort" if scheduler_node_port else "ClusterIP",
                    "selector": labels,
                    "ports": [
                        {"name": "tcp-comm", "protocol": "TCP", "port": SCHEDULER_PORT, "targetPort": "tcp-comm",
                         **({"nodePort": scheduler_node_port} if scheduler_node_port else {})},
                        {"name": "http-dashboard", "protocol": "TCP", "port": DASHBOARD_PORT,
                         "targetPort": "http-dashboard",
                         **({"nodePort": dashboard_node_port} if scheduler_node_port and dashboard_node_port
                            else {})},
                    ],
                },
            },
        },
    }
    if idle_timeout:
        spec["spec"]["idleTimeout"] = idle_timeout
    return spec


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


_kube_cluster_class = None


def kube_cluster_class():
    """dask_kubernetes' operator KubeCluster, working around a status race in the operator.

    The Dask Kubernetes Operator (2026.3.0) sets the DaskCluster's
    status.phase to Running when the scheduler Service is created, then its
    create-components handler finishes and sets it back to Pending. A
    ClusterIP Service never changes again, so the phase can stay Pending and
    KubeCluster times out waiting for Running. The operator only sets Pending
    after creating all components, and KubeCluster then waits for the
    scheduler pod, Service and connection anyway, so accept either phase.
    """
    global _kube_cluster_class
    if _kube_cluster_class is None:
        from dask_kubernetes.operator import KubeCluster
        from dask_kubernetes.operator._objects import DaskCluster

        class OperatorKubeCluster(KubeCluster):
            async def _wait_for_controller(self):
                start = time.time()
                cluster = await DaskCluster.get(self.name, namespace=self.namespace, timeout=30)
                while start + self._resource_timeout > time.time():
                    await cluster.async_refresh()
                    if cluster.raw.get("status", {}).get("phase") in ("Pending", "Running"):
                        return
                    await asyncio.sleep(0.25)
                raise TimeoutError(
                    f"Dask Cluster resource not actioned after {self._resource_timeout} seconds, "
                    "is the Dask Operator running?"
                )

        _kube_cluster_class = OperatorKubeCluster
    return _kube_cluster_class


def gpu_cluster(name: str, n_workers: int, gpu_memory_gib: int, namespace: Optional[str] = None,
                **spec_options):
    """Create a Dask cluster whose GPU workers scale between 0 and ``n_workers``.

    Returns a ``dask_kubernetes.operator.KubeCluster``; the cluster is deleted
    when it is closed or the client process exits. ``namespace`` defaults to
    the client pod's namespace in the cluster, or the kubeconfig's current
    namespace outside it. See ``gpu_cluster_spec`` for ``spec_options``.
    """
    cluster = kube_cluster_class()(
        custom_cluster_spec=gpu_cluster_spec(name, gpu_memory_gib, **spec_options),
        namespace=namespace or default_namespace(),
        shutdown_on_close=True,
    )
    cluster.adapt(minimum=0, maximum=n_workers)
    return cluster


def standing_cluster_manifests(
    name: str,
    n_workers: int,
    gpu_memory_gib: int,
    dashboard_host: Optional[str] = None,
    ingress_class: Optional[str] = "traefik",
    **spec_options,
) -> List[dict]:
    """A long-lived GPU Dask cluster that clients reach by address.

    Returns the DaskCluster, a DaskAutoscaler that keeps its GPU workers
    between 0 and ``n_workers`` (the scheduler asks for workers as clients
    submit tasks, and idle ones are removed), and an Ingress for the
    scheduler dashboard at ``dashboard_host`` (default
    ``<name>.dask.localhost``) through ``ingress_class`` (``traefik`` in the
    lab; None for no Ingress, on clusters without one). The scheduler is the
    Service ``<name>-scheduler``, port 8786; with ``scheduler_node_port`` also
    that port on every node. See ``gpu_cluster_spec`` for ``spec_options``.
    """
    cluster = gpu_cluster_spec(name, gpu_memory_gib, **spec_options)
    labels = {"dask.org/cluster-name": name}
    autoscaler = {
        "apiVersion": "kubernetes.dask.org/v1",
        "kind": "DaskAutoscaler",
        "metadata": {"name": name, "labels": labels},
        "spec": {"cluster": name, "minimum": 0, "maximum": n_workers},
    }
    ingress = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {"name": f"{name}-dashboard", "labels": labels},
        "spec": {
            "ingressClassName": ingress_class,
            "rules": [{
                "host": dashboard_host or f"{name}.dask.localhost",
                "http": {"paths": [{
                    "path": "/",
                    "pathType": "Prefix",
                    "backend": {"service": {"name": f"{name}-scheduler", "port": {"number": DASHBOARD_PORT}}},
                }]},
            }],
        },
    }
    return [cluster, autoscaler] + ([ingress] if ingress_class else [])


def parse_selector(text: Optional[str]) -> Optional[Dict[str, str]]:
    """``KEY=VALUE,KEY=VALUE`` as a node selector; None as None."""
    if text is None:
        return None
    selector = {}
    for item in text.split(","):
        if item.strip():
            key, _, value = item.partition("=")
            selector[key.strip()] = value.strip()
    return selector


def parse_tolerations(items: Optional[List[str]]) -> Optional[List[dict]]:
    """``KEY[=VALUE][:EFFECT]`` items as tolerations; ``["none"]`` as []; None as None."""
    if items is None:
        return None
    tolerations = []
    for item in items:
        if item.strip().lower() == "none":
            continue
        key, _, effect = item.partition(":")
        key, has_value, value = key.partition("=")
        toleration = {"key": key.strip(), "operator": "Equal" if has_value else "Exists"}
        if has_value:
            toleration["value"] = value.strip()
        if effect:
            toleration["effect"] = effect.strip()
        tolerations.append(toleration)
    return tolerations


def main(argv: Optional[List[str]] = None) -> int:
    """Print the manifests of a standing GPU Dask cluster as a Kubernetes List (JSON)."""
    parser = argparse.ArgumentParser(
        description="Print a standing GPU Dask cluster for `devlab kubectl apply -n dask -f -`. "
                    "Clients connect to tcp://<host IP>:8786 from other machines, "
                    "tcp://localhost:8786 on the Docker host, "
                    "tcp://dev-lab-control-plane:30786 on the kind network, or "
                    "tcp://NAME-scheduler.dask:8786 in the cluster.")
    parser.add_argument("name", help="cluster name; the scheduler Service is NAME-scheduler")
    parser.add_argument("--workers", type=int, default=4, help="most GPU workers at once (default 4)")
    parser.add_argument("--gpu-memory-gib", type=int, default=5,
                        help="GPU memory per worker in GiB (default 5); with time slicing also its nvidia.com/gpu shares")
    parser.add_argument("--gpu-shares", type=int, default=None,
                        help="nvidia.com/gpu shares per worker when not one per GiB, e.g. 1 with MPS (see GPU.md)")
    parser.add_argument("--task-duration", default="1m",
                        help="how long the scheduler assumes a task takes until it has measured it; anything "
                             "over a few seconds starts one worker per queued task (default 1m)")
    parser.add_argument("--rmm-pool", action="store_true",
                        help="fixed RMM pool per worker, for code that allocates through RMM (not XGBoost)")
    parser.add_argument("--host-memory", default="8Gi", help="host memory limit per worker (default 8Gi)")
    parser.add_argument("--resources", default="GPU=1",
                        help="Dask worker resources for tasks submitted with resources={...}, "
                             "comma-separated NAME=AMOUNT (default GPU=1); none for no resources")
    parser.add_argument("--node-port", type=int, default=STANDING_SCHEDULER_NODE_PORT,
                        help=f"scheduler NodePort; {STANDING_SCHEDULER_NODE_PORT} (default) is published "
                             "as port 8786 of the Docker host. Only one cluster can use a port; "
                             "0 for none (in-cluster clients only)")
    parser.add_argument("--dashboard-node-port", type=int, default=STANDING_DASHBOARD_NODE_PORT,
                        help=f"dashboard NodePort with --node-port; {STANDING_DASHBOARD_NODE_PORT} (default) is "
                             "published as port 8787 of the Docker host (http://<host IP>:8787/workers); "
                             "0 for a random one")
    parser.add_argument("--image", default=IMAGE)
    placement = parser.add_argument_group("placement", "for clusters other than the lab's (e.g. AKS; see the runbook)")
    placement.add_argument("--worker-node-selector", metavar="KEY=VALUE[,KEY=VALUE]", default=None,
                           help="node labels for the GPU workers (default devlab.io/gpu=true)")
    placement.add_argument("--worker-toleration", metavar="KEY[=VALUE][:EFFECT]", action="append", default=None,
                           help="taint the workers tolerate, repeatable, e.g. sku=gpu:NoSchedule "
                                "(default nvidia.com/gpu:NoSchedule); none for no tolerations")
    placement.add_argument("--scheduler-node-selector", metavar="KEY=VALUE[,KEY=VALUE]", default=None,
                           help="node labels for the scheduler (default devlab.io/gpu=false)")
    placement.add_argument("--scheduler-toleration", metavar="KEY[=VALUE][:EFFECT]", action="append", default=None,
                           help="taint the scheduler tolerates, repeatable (default none)")
    placement.add_argument("--runtime-class", default="nvidia",
                           help="RuntimeClass of the worker pods (default nvidia, from the GPU Operator); "
                                "none where the default runtime has the GPU hooks, as on AKS")
    placement.add_argument("--one-worker-per-node", action="store_true",
                           help="required anti-affinity between the workers: one per node, for pools "
                                "with one GPU per node")
    placement.add_argument("--worker-cpu", default="500m", help="CPU request per worker (default 500m)")
    placement.add_argument("--ingress-class", default="traefik",
                           help="IngressClass of the dashboard Ingress (default traefik, the lab's); "
                                "none for no Ingress")
    args = parser.parse_args(argv)

    worker_resources = {} if args.resources.strip().lower() in ("", "none") else dict(
        (key.strip(), float(value)) for key, value in (item.split("=", 1) for item in args.resources.split(",") if item)
    )
    items = standing_cluster_manifests(
        args.name, args.workers, args.gpu_memory_gib,
        gpu_shares=args.gpu_shares, image=args.image, host_memory=args.host_memory, rmm_pool=args.rmm_pool,
        unknown_task_duration=args.task_duration, worker_resources=worker_resources,
        scheduler_node_port=args.node_port or None,
        dashboard_node_port=args.dashboard_node_port or None,
        worker_node_selector=parse_selector(args.worker_node_selector),
        worker_tolerations=parse_tolerations(args.worker_toleration),
        scheduler_node_selector=parse_selector(args.scheduler_node_selector),
        scheduler_tolerations=parse_tolerations(args.scheduler_toleration),
        runtime_class=None if args.runtime_class.lower() == "none" else args.runtime_class,
        one_worker_per_node=args.one_worker_per_node,
        worker_cpu=args.worker_cpu,
        ingress_class=None if args.ingress_class.lower() == "none" else args.ingress_class,
    )
    json.dump({"apiVersion": "v1", "kind": "List", "items": items}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
