"""Dagster code location: jobs that run on time-sliced GPU Dask clusters (devlab addon enable dagster).

Launch a job from the Dagster UI (http://dagster.localhost > Jobs > the job >
Launchpad > Launch Run). Every job uses dagster-dask's ``dask_executor``:

1. The run is a Kubernetes pod in the dask namespace (K8sRunLauncher).
2. The executor creates a Dask cluster for the run with
   ``devlab_dask.gpu_cluster``: a scheduler on a CPU node and 0 GPU workers.
3. Each op becomes one Dask task. The scheduler starts a GPU worker per op
   that can run (up to ``n_workers``), each with ``gpu_memory_gib`` GiB of a
   time-sliced GPU, and removes them when idle.
4. Op outputs go through PostgreSQL (postgres_io_manager.py), so ops on
   different workers can pass data. The cluster is deleted when the run ends.

The cluster shape is the executor config in the Launchpad (defaults below):

    execution:
      config:
        cluster:
          kube:
            n_workers: 4
            gpu_memory_gib: 5
            # gpu_shares: 1   # with MPS (GPU.md): 1 share, a fixed slice of the GPU

This file, postgres_io_manager.py, devlab_dask.py and the sample's
gpu_concurrency.py are mounted from ConfigMaps (config/dask/kustomization.yaml)
into the code location, the run pods and the Dask workers. After changing
them, run ``devlab kubectl apply -k config/dask`` and reload the code location
in the UI (Deployment > devlab-dask > Reload) once the pods see the new files.
"""

import re
import secrets
from typing import List, Optional

import dagster as dg
import dask_kubernetes
from dagster_dask import dask_executor

import devlab_dask
import gpu_concurrency
from postgres_io_manager import PostgresPickleIOManager

# Workers run the ops, so they get the same code and Dagster instance access
# as the run pods (config/addons/dagster/values.yaml)
WORKER_VOLUMES = [
    {"name": "devlab-dask", "configMap": {"name": "devlab-dask"}},
    {"name": "devlab-dagster", "configMap": {"name": "devlab-dagster"}},
]
WORKER_VOLUME_MOUNTS = [
    {"name": "devlab-dask", "mountPath": "/devlab"},
    {"name": "devlab-dagster", "mountPath": "/dagster"},
]
WORKER_ENV = [
    {"name": "PYTHONPATH", "value": "/devlab:/dagster"},
    # Workers record their ops' events in the Dagster instance (PostgreSQL)
    {"name": "DAGSTER_PG_PASSWORD",
     "valueFrom": {"secretKeyRef": {"name": "dagster-postgresql-secret", "key": "postgresql-password"}}},
]

DEFAULT_CLUSTER = {"n_workers": 4, "gpu_memory_gib": 5}


def cluster_name(job_name: str) -> str:
    """Unique DaskCluster name for a run of a job: lowercase, dashes, at most 37 characters."""
    base = re.sub(r"[^a-z0-9]+", "-", job_name.lower()).strip("-")[:30] or "dagster"
    return f"{base}-{secrets.token_hex(3)}"


def gpu_kube_cluster(name: str, n_workers: int = DEFAULT_CLUSTER["n_workers"],
                     gpu_memory_gib: int = DEFAULT_CLUSTER["gpu_memory_gib"], gpu_shares: Optional[int] = None,
                     rmm_pool: bool = False,
                     host_memory: str = "8Gi", op_duration: str = "5m", idle_timeout: int = 600):
    """The ``kube`` cluster of dask_executor: a time-sliced GPU Dask cluster for one run.

    dask_executor calls ``KubeCluster(name=<job name>, **cluster config)`` and
    never closes it; dask-kubernetes deletes it when the run pod exits, and
    ``idle_timeout`` (seconds) removes it if the run pod is killed.
    ``op_duration`` is how long the scheduler assumes an op takes; anything
    over a few seconds makes it start one worker per op that can run.
    ``rmm_pool`` is off because XGBoost does not allocate through RMM.
    """
    return devlab_dask.gpu_cluster(
        cluster_name(name),
        n_workers=n_workers,
        gpu_memory_gib=gpu_memory_gib,
        gpu_shares=gpu_shares,
        rmm_pool=rmm_pool,
        host_memory=host_memory,
        unknown_task_duration=op_duration,
        idle_timeout=idle_timeout,
        worker_env=WORKER_ENV,
        worker_volumes=WORKER_VOLUMES,
        worker_volume_mounts=WORKER_VOLUME_MOUNTS,
    )


# dagster_dask's `kube` cluster type creates `dask_kubernetes.KubeCluster`,
# which dask-kubernetes no longer provides at the top level
dask_kubernetes.KubeCluster = gpu_kube_cluster


def cluster_config(**overrides) -> dict:
    """Run config selecting the GPU Dask cluster, editable in the Launchpad."""
    return {"execution": {"config": {"cluster": {"kube": {**DEFAULT_CLUSTER, **overrides}}}}}


def run_cluster_config(context: dg.OpExecutionContext) -> dict:
    return {**DEFAULT_CLUSTER, **context.run_config["execution"]["config"]["cluster"].get("kube", {})}


# Example from dagster-dask-integration-example: data passed between two ops
# running on Dask workers


@dg.op
def generate_data() -> List[int]:
    return list(range(100))


@dg.op
def compute_squares(numbers: List[int]) -> List[int]:
    import dask.bag as db

    return db.from_sequence(numbers).map(lambda x: x ** 2).compute()


@dg.job(
    executor_def=dask_executor,
    config=cluster_config(n_workers=1, gpu_memory_gib=1),
    description="Two ops on a Dask worker, passing data through PostgreSQL",
)
def squares_job():
    compute_squares(generate_data())


# GPU time slicing: GPU_TASKS ops at once, each on its own worker sharing the GPU

GPU_TASKS = 4


class GPUTaskSettings(dg.ConfigurableResource):
    # How long each op keeps its GPU busy training XGBoost models
    seconds: float = 30
    # "cpu" runs the same ops without a GPU
    device: str = "cuda"


def gpu_task_op(index: int) -> dg.OpDefinition:
    @dg.op(name=f"gpu_task_{index}")
    def gpu_task(context: dg.OpExecutionContext, gpu_task_settings: GPUTaskSettings) -> dict:
        """Wait until the other GPU ops' workers are up, then train XGBoost on this worker's GPU share."""
        at_once = min(GPU_TASKS, run_cluster_config(context)["n_workers"])
        result = gpu_concurrency.gpu_task(gpu_task_settings.seconds, at_once, gpu_task_settings.device)
        context.log.info(f"{result['worker']} on GPU {result['gpu']}: {result['rounds']} rounds")
        return result

    return gpu_task


GPU_TASK_OPS = [gpu_task_op(index) for index in range(GPU_TASKS)]


# One input per GPU op: dask_executor runs every op in a fresh process, where a
# fan-in input (a list of upstream outputs) loads as an empty list
@dg.op(ins={f"result_{index}": dg.In(dict) for index in range(GPU_TASKS)})
def check_gpu_concurrency(context: dg.OpExecutionContext, **inputs: dict) -> str:
    """Fails unless every GPU op ran on its own worker, all at the same time."""
    results = list(inputs.values())
    started = min(result["joined"] for result in results)
    context.log.info("\n" + gpu_concurrency.timeline(results, started))
    n_workers = run_cluster_config(context)["n_workers"]
    if n_workers < len(results):
        message = f"n_workers={n_workers} is less than {len(results)} ops, so they could not all run at once"
        context.log.warning(message)
        return message
    ok, message = gpu_concurrency.check_concurrent(results, len(results))
    if not ok:
        raise dg.Failure(message)
    context.add_output_metadata({
        "workers": len({result["worker"] for result in results}),
        "gpus": ", ".join(sorted({result["gpu"] for result in results})),
        "scale_up_seconds": round(gpu_concurrency.scale_up_seconds(results, started), 1),
    })
    return message


@dg.job(
    executor_def=dask_executor,
    config=cluster_config(),
    description=f"{GPU_TASKS} XGBoost ops sharing one GPU through time slicing, from 0 workers",
)
def gpu_concurrency_job():
    check_gpu_concurrency(**{f"result_{index}": op() for index, op in enumerate(GPU_TASK_OPS)})


defs = dg.Definitions(
    jobs=[squares_job, gpu_concurrency_job],
    resources={
        "io_manager": PostgresPickleIOManager(),
        "gpu_task_settings": GPUTaskSettings(),
    },
)
