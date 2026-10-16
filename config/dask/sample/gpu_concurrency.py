"""Run one GPU task on every Dask worker at the same time and check they overlapped.

Each task runs CuPy matrix multiplies for TASK_SECONDS on its worker's GPU share,
then reports when it started and finished. With time slicing, all tasks run on
the same physical GPU, so the timeline shows them sharing it concurrently.

Environment:
    DASK_SCHEDULER_ADDRESS  scheduler to connect to (tcp://dask-scheduler:8786)
    EXPECTED_WORKERS        workers to wait for and use (4)
    TASK_SECONDS            how long each task keeps its GPU busy (30)
    MATRIX_SIZE             square matrix size per task (4096, ~64 MiB float32)

Exit code is 0 when every task ran on a different worker and all of them were
running at the same moment, 1 otherwise.
"""

import os
import sys
import time


def gpu_task(seconds, size):
    """Keep this worker's GPU share busy and report what ran where"""
    import cupy
    import rmm
    from distributed import get_worker

    start = time.time()
    matrix = cupy.random.random((size, size), dtype=cupy.float32)
    iterations = 0
    while time.time() - start < seconds:
        matrix = matrix @ matrix
        matrix /= cupy.linalg.norm(matrix)
        cupy.cuda.Device().synchronize()
        iterations += 1
    end = time.time()

    return {
        "worker": get_worker().name,
        "pid": os.getpid(),
        # The device plugin sets this to the physical GPU behind the share
        "gpu": os.environ.get("NVIDIA_VISIBLE_DEVICES", "?"),
        "memory_resource": type(rmm.mr.get_current_device_resource()).__name__,
        "start": start,
        "end": end,
        "iterations": iterations,
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


def run(client, expected_workers, task, *task_args):
    """Submit one task pinned to each of the first expected_workers workers"""
    client.wait_for_workers(expected_workers, timeout=600)
    # client.run returns {worker address: result} for every connected worker
    addresses = sorted(client.run(os.getpid))[:expected_workers]
    futures = [
        client.submit(task, *task_args, workers=[address], allow_other_workers=False, pure=False)
        for address in addresses
    ]
    return client.gather(futures)


def print_timeline(results):
    origin = min(result["start"] for result in results)
    print(f"{'worker':<40} {'gpu':<44} {'start':>6} {'end':>6} {'iters':>6}  memory resource")
    for result in sorted(results, key=lambda r: r["worker"]):
        print(f"{result['worker']:<40} {result['gpu']:<44} "
              f"{result['start'] - origin:>5.1f}s {result['end'] - origin:>5.1f}s "
              f"{result['iterations']:>6}  {result.get('memory_resource', '-')}")


def main():
    from dask.distributed import Client

    address = os.environ.get("DASK_SCHEDULER_ADDRESS", "tcp://dask-scheduler:8786")
    expected_workers = int(os.environ.get("EXPECTED_WORKERS", "4"))
    seconds = float(os.environ.get("TASK_SECONDS", "30"))
    size = int(os.environ.get("MATRIX_SIZE", "4096"))

    print(f"Connecting to {address}, waiting for {expected_workers} workers...", flush=True)
    with Client(address) as client:
        print(f"Running a {seconds:.0f}s GPU task on each worker...", flush=True)
        results = run(client, expected_workers, gpu_task, seconds, size)

    print_timeline(results)
    ok, message = check_concurrent(results, expected_workers)
    print(("PASS: " if ok else "FAIL: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
