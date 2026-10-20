"""Scale a GPU Dask cluster from 0 workers for GPU tasks and check they ran concurrently.

Creates a cluster with devlab_dask.gpu_cluster (0 workers, adapting up to
N_WORKERS), submits one GPU task per worker, and lets the scheduler and the
Dask Kubernetes Operator start the workers. Each task waits until all workers
have joined, then keeps its GPU share busy training XGBoost models on the GPU
for TASK_SECONDS and reports when it ran. With time slicing, all tasks run on the
same physical GPU at once. The cluster is deleted at the end; idle workers
are removed before that by the autoscaler.

With SCHEDULER_ADDRESS set, it connects to that scheduler instead, e.g. a
standing cluster (DASK-GPU-RUNBOOK.md, "Connect Existing Clients By Address"),
and needs only dask and distributed on the client side:

    SCHEDULER_ADDRESS=tcp://<server IP>:8786 python gpu_concurrency.py

Environment:
    SCHEDULER_ADDRESS  existing scheduler to use instead of creating a cluster
    N_WORKERS        workers to scale up to and tasks to run (4); with
                     SCHEDULER_ADDRESS at most the cluster's --workers
    GPU_MEMORY_GIB   GPU memory per worker = nvidia.com/gpu shares (5)
    TASK_SECONDS     how long each task keeps its GPU busy (30)
    CLUSTER_NAME     name of the DaskCluster to create (gpu-concurrency)
    DEVICE           XGBoost device (cuda); cpu runs the check without a GPU

Exit code is 0 when every task ran on a different worker and all of them were
running at the same moment, 1 otherwise.
"""

import os
import sys
import time

# Name of the task function below: the scheduler is told how long these tasks
# take (task_durations), so it asks for all workers at once
TASK_NAME = "gpu_task"

# Training data per task: 200k rows x 32 float32 features (25 MB), small
# enough for the smallest worker (GPU_MEMORY_GIB=2)
ROWS = 200_000
COLUMNS = 32
ROUNDS_PER_TRAIN = 10


def gpu_task(seconds, n_workers, device="cuda"):
    """Wait for all workers, then keep this worker's GPU share busy and report what ran where"""
    import numpy as np
    import xgboost as xgb
    from distributed import get_client, get_worker

    joined = time.time()
    # All tasks start computing together once every worker is up
    get_client().wait_for_workers(n_workers, timeout=900)
    ready = time.time()

    rng = np.random.default_rng()
    features = rng.random((ROWS, COLUMNS), dtype=np.float32)
    labels = features @ rng.random(COLUMNS, dtype=np.float32) + rng.normal(0, 0.1, ROWS).astype(np.float32)
    data = xgb.QuantileDMatrix(features, labels)
    params = {"device": device, "tree_method": "hist", "max_depth": 8, "objective": "reg:squarederror"}
    rounds = 0
    start = time.time()
    while time.time() - start < seconds:
        xgb.train(params, data, num_boost_round=ROUNDS_PER_TRAIN)
        rounds += ROUNDS_PER_TRAIN
    end = time.time()

    return {
        "worker": get_worker().name,
        # The device plugin sets this to the physical GPU behind the shares
        "gpu": os.environ.get("NVIDIA_VISIBLE_DEVICES", "?"),
        "joined": joined,
        "ready": ready,
        "start": start,
        "end": end,
        "rounds": rounds,
    }



def check_concurrent(results, expected_workers):
    """Return (ok, message): one task per worker, all running at one moment"""
    workers = {result["worker"] for result in results}
    if len(results) < expected_workers or len(workers) < expected_workers:
        return False, (f"expected {expected_workers} tasks on {expected_workers} workers, "
                       f"got {len(results)} tasks on {len(workers)} workers")
    latest_start = max(result["start"] for result in results)
    earliest_end = min(result["end"] for result in results)
    overlap = earliest_end - latest_start
    if overlap <= 0:
        return False, "tasks did not overlap: they ran one after another"
    return True, f"all {len(results)} tasks were running at the same time for {overlap:.1f}s"


def run(client, n_workers, task, *task_args, resources=None):
    """Submit n_workers tasks, e.g. needing a whole worker each (resources={"GPU": 1})."""
    futures = [
        client.submit(task, *task_args, resources=resources, pure=False)
        for _ in range(n_workers)
    ]
    return client.gather(futures)


def timeline(results, submitted):
    """When each task joined, started and ended, relative to submitting them"""
    lines = [f"{'worker':<44} {'joined':>7} {'start':>6} {'end':>6} {'rounds':>6}"]
    for result in sorted(results, key=lambda r: r["start"]):
        lines.append(f"{result['worker']:<44} {result['joined'] - submitted:>6.1f}s "
                     f"{result['start'] - submitted:>5.1f}s {result['end'] - submitted:>5.1f}s "
                     f"{result['rounds']:>6}")
    lines.append(f"GPU(s): {', '.join(sorted({result['gpu'] for result in results}))}")
    lines.append(f"Scale-up: {scale_up_seconds(results, submitted):.1f}s "
                 "from submitting the tasks to all workers running them")
    return "\n".join(lines)


def scale_up_seconds(results, submitted):
    """Seconds from submitting the tasks until the last worker was running its task"""
    return max(result["ready"] for result in results) - submitted


def print_timeline(results, submitted):
    print(timeline(results, submitted))


def main():
    from dask.distributed import Client

    n_workers = int(os.environ.get("N_WORKERS", "4"))
    gpu_memory_gib = int(os.environ.get("GPU_MEMORY_GIB", "5"))
    seconds = float(os.environ.get("TASK_SECONDS", "30"))
    name = os.environ.get("CLUSTER_NAME", "gpu-concurrency")
    device = os.environ.get("DEVICE", "cuda")
    address = os.environ.get("SCHEDULER_ADDRESS")

    if address:
        print(f"Connecting to {address}", flush=True)
        with Client(address) as client:
            print(f"Scheduler has {len(client.scheduler_info()['workers'])} workers; "
                  f"submitting {n_workers} GPU tasks...", flush=True)
            submitted = time.time()
            # Each worker runs one task at a time (--nthreads 1); no resources,
            # so this also works on a standing cluster made with --resources none
            results = run(client, n_workers, gpu_task, seconds, n_workers, device)
        return report(results, submitted, n_workers)

    from devlab_dask import gpu_cluster

    print(f"Creating Dask cluster {name}: 0 to {n_workers} GPU workers, {gpu_memory_gib} GiB GPU memory each",
          flush=True)
    with gpu_cluster(name, n_workers=n_workers, gpu_memory_gib=gpu_memory_gib,
                     task_durations={TASK_NAME: f"{seconds:g}s"},
                     worker_resources={"GPU": 1},
                     # XGBoost allocates GPU memory itself, not through RMM
                     rmm_pool=False) as cluster, Client(cluster) as client:
        print(f"Scheduler up with {len(client.scheduler_info()['workers'])} workers; "
              f"submitting {n_workers} GPU tasks...", flush=True)
        submitted = time.time()
        results = run(client, n_workers, gpu_task, seconds, n_workers, device, resources={"GPU": 1})

    return report(results, submitted, n_workers)


def report(results, submitted, n_workers):
    print_timeline(results, submitted)
    ok, message = check_concurrent(results, n_workers)
    print(("PASS: " if ok else "FAIL: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
