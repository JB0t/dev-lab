"""GPU stress test: a grid of gradient-boosting fits at once on a Dask GPU cluster.

Like a model-fitting job: FITS models with different hyper-parameters are
trained on synthetic data, one per worker at a time, each with a validation
set. The data is bigger and the trees deeper than in gpu_concurrency.py, so
each fit keeps its GPU share busy with long kernels instead of launch
overhead. The throughput to compare is the total rounds/s:

    N_WORKERS=1 ... python gpu_stress.py      # one fit at a time: the GPU alone
    N_WORKERS=4 ... python gpu_stress.py      # four at once

Like a grid search, the fits share DATASETS datasets (1 by default). A worker
keeps the dataset of its last fit on the GPU, so a fit on the same data skips
building it (the quantile sketch and the copy to the GPU: the "build" column)
and uses the worker's GPU memory to hold data instead of leaving it idle.
DATASETS=FITS gives every fit its own data, built every time.

Time slicing: four workers share one worker's rounds/s. MPS: the total
grows until the GPU is full. Watch the GPU on the host meanwhile with
`nvidia-smi dmon -s um`.

With SCHEDULER_ADDRESS set, the fits run on that scheduler, e.g. the standing
cluster (DASK-GPU-RUNBOOK.md); the client then needs only dask and distributed.
Without it, a cluster is created with devlab_dask.gpu_cluster.

Environment:
    SCHEDULER_ADDRESS  existing scheduler to use instead of creating a cluster
    N_WORKERS        workers to use (4); with SCHEDULER_ADDRESS at most the
                     cluster's --workers
    FITS             models to fit (8); each worker fits FITS / N_WORKERS
    DATASETS         datasets the fits share (1); fit i uses dataset i % DATASETS
    ROWS, COLUMNS    training data per fit (2000000 x 64 float32, 512 MB)
    MAX_DEPTH        tree depth (10)
    ROUNDS           boosting rounds per fit (200)
    LIBRARY          xgboost (default) or lightgbm (needs LightGBM built with
                     CUDA; the pip wheel in the default image is CPU-only)
    GPU_MEMORY_GIB   GPU memory per worker in GiB (5), when creating a cluster;
                     with time slicing also its nvidia.com/gpu shares
    GPU_SHARES       nvidia.com/gpu shares per worker when not one per GiB,
                     e.g. 1 with MPS (GPU.md)
    CLUSTER_NAME     name of the DaskCluster to create (gpu-stress)
    DEVICE           cuda (default); cpu runs the test without a GPU

Exit code is 0 when every fit completed, 1 otherwise.
"""

import os
import sys
import time

TASK_NAME = "fit"

# Hyper-parameter grid, cycled through by fit number
GRID = [
    {"learning_rate": 0.05, "colsample": 1.0},
    {"learning_rate": 0.1, "colsample": 0.8},
    {"learning_rate": 0.2, "colsample": 0.6},
    {"learning_rate": 0.1, "colsample": 1.0},
]


def make_data(index, rows, columns):
    """Synthetic regression data with non-linear structure, different per fit"""
    import numpy as np

    rng = np.random.default_rng(index)
    features = rng.random((rows, columns), dtype=np.float32)
    weights = rng.random(columns, dtype=np.float32)
    target = (features @ weights
              + 2 * np.sin(features[:, 0] * 6)
              + 3 * (features[:, 1] > 0.5) * features[:, 2]
              + rng.normal(0, 0.1, rows)).astype(np.float32)
    return features, target


def build(library, device, dataset, rows, columns):
    """The library's train and valid sets for a dataset, ready for any number of fits"""
    features, target = make_data(dataset, rows, columns)
    split = int(rows * 0.8)
    if library == "xgboost":
        import xgboost as xgb

        train = xgb.QuantileDMatrix(features[:split], target[:split])
        valid = xgb.QuantileDMatrix(features[split:], target[split:], ref=train)
    elif library == "lightgbm":
        import lightgbm as lgb

        params = {"device_type": device if device == "cuda" else "cpu", "verbose": -1}
        train = lgb.Dataset(features[:split], target[:split], params=params, free_raw_data=False)
        valid = lgb.Dataset(features[split:], target[split:], reference=train, free_raw_data=False)
        train.construct()
        valid.construct()
    else:
        raise ValueError(f"LIBRARY must be xgboost or lightgbm, not {library!r}")
    return train, valid


def cached_data(worker, key, make):
    """The worker's one cached dataset: built by make() when the key is new, else as it is"""
    cache = worker.__dict__.setdefault("gpu_stress_data", {})
    if cache.get("key") != key:
        cache.clear()  # free the old dataset's GPU memory before building the new one
        cache["key"], cache["data"] = key, make()
        return cache["data"], False
    return cache["data"], True


def fit(index, datasets, rows, columns, max_depth, rounds, library="xgboost", device="cuda"):
    """Train one model on this worker's GPU share and report how it went"""
    from distributed import get_worker

    worker = get_worker()
    grid = GRID[index % len(GRID)]
    dataset = index % datasets
    start = time.time()
    (train, valid), cached = cached_data(worker, (library, device, dataset, rows, columns),
                                         lambda: build(library, device, dataset, rows, columns))
    built = time.time()
    if library == "xgboost":
        import xgboost as xgb

        params = {"device": device, "tree_method": "hist", "objective": "reg:squarederror",
                  "max_depth": max_depth, "learning_rate": grid["learning_rate"],
                  "colsample_bytree": grid["colsample"], "subsample": 0.8}
        history = {}
        booster = xgb.train(params, train, num_boost_round=rounds, evals=[(valid, "valid")],
                            evals_result=history, verbose_eval=False)
        trained = booster.num_boosted_rounds()
        rmse = history["valid"]["rmse"][-1]
    else:
        import lightgbm as lgb

        params = {"device_type": device if device == "cuda" else "cpu", "objective": "regression",
                  "max_depth": max_depth, "num_leaves": min(2 ** max_depth, 255),
                  "learning_rate": grid["learning_rate"], "feature_fraction": grid["colsample"],
                  "bagging_fraction": 0.8, "bagging_freq": 1, "verbose": -1}
        history = {}
        booster = lgb.train(params, train, num_boost_round=rounds, valid_sets=[valid],
                            callbacks=[lgb.record_evaluation(history)])
        trained = booster.current_iteration()
        rmse = history["valid_0"]["l2"][-1] ** 0.5
    end = time.time()
    return {
        "fit": index,
        "dataset": dataset,
        "worker": worker.name,
        "gpu": os.environ.get("NVIDIA_VISIBLE_DEVICES", "?"),
        "start": start,
        "built": built,
        "cached": cached,
        "end": end,
        "rounds": trained,
        "rmse": rmse,
        **grid,
    }


def summary(results, submitted):
    """Per-fit table, then the throughput and how many fits ran at once"""
    lines = [f"{'fit':>3} {'data':>4} {'worker':<40} {'start':>7} {'build':>6} {'end':>7} {'rounds':>6} {'rounds/s':>8} "
             f"{'rmse':>7}  params"]
    for result in sorted(results, key=lambda r: r["start"]):
        build_seconds = result["built"] - result["start"]
        seconds = result["end"] - result["built"]
        lines.append(f"{result['fit']:>3} {result['dataset']:>4} {result['worker']:<40} {result['start'] - submitted:>6.1f}s "
                     f"{'cached' if result['cached'] else f'{build_seconds:5.1f}s':>6} "
                     f"{result['end'] - submitted:>6.1f}s {result['rounds']:>6} {result['rounds'] / seconds:>8.1f} "
                     f"{result['rmse']:>7.3f}  lr={result['learning_rate']} colsample={result['colsample']}")
    total_rounds = sum(result["rounds"] for result in results)
    wall = max(result["end"] for result in results) - min(result["start"] for result in results)
    built = [result for result in results if not result["cached"]]
    lines.append(f"GPU(s): {', '.join(sorted({result['gpu'] for result in results}))}")
    lines.append(f"Data: built {len(built)} times, {sum(r['built'] - r['start'] for r in built):.1f}s in all; "
                 f"cached for {len(results) - len(built)} fits")
    lines.append(f"Workers: {len({result['worker'] for result in results})}, "
                 f"at most {peak_concurrency(results)} fits at once")
    lines.append(f"Throughput: {total_rounds} rounds in {wall:.1f}s = {total_rounds / wall:.1f} rounds/s")
    return "\n".join(lines)


def peak_concurrency(results):
    """Most fits running at one moment"""
    events = sorted([(result["start"], 1) for result in results] + [(result["end"], -1) for result in results])
    running = peak = 0
    for _, change in events:
        running += change
        peak = max(peak, running)
    return peak


def run(client, fits, *task_args):
    """Submit the fits; each worker takes one at a time (--nthreads 1)

    Fits are not grouped by dataset: a worker builds a dataset again when a fit on
    another one came between, as a plain grid search over several datasets would.
    """
    futures = [client.submit(fit, index, *task_args, pure=False) for index in range(fits)]
    return client.gather(futures)


def main():
    from dask.distributed import Client

    n_workers = int(os.environ.get("N_WORKERS", "4"))
    fits = int(os.environ.get("FITS", "8"))
    datasets = int(os.environ.get("DATASETS", "1"))
    rows = int(os.environ.get("ROWS", "2000000"))
    columns = int(os.environ.get("COLUMNS", "64"))
    max_depth = int(os.environ.get("MAX_DEPTH", "10"))
    rounds = int(os.environ.get("ROUNDS", "200"))
    library = os.environ.get("LIBRARY", "xgboost")
    device = os.environ.get("DEVICE", "cuda")
    gpu_memory_gib = int(os.environ.get("GPU_MEMORY_GIB", "5"))
    gpu_shares = int(os.environ["GPU_SHARES"]) if os.environ.get("GPU_SHARES") else None
    name = os.environ.get("CLUSTER_NAME", "gpu-stress")
    address = os.environ.get("SCHEDULER_ADDRESS")
    task_args = (datasets, rows, columns, max_depth, rounds, library, device)
    print(f"{fits} {library} fits of {rounds} rounds, depth {max_depth}, on {datasets} dataset(s) of {rows} x {columns}; "
          f"{n_workers} workers", flush=True)

    if address:
        print(f"Connecting to {address}", flush=True)
        with Client(address) as client:
            submitted = time.time()
            results = run(client, fits, *task_args)
        return report(results, submitted, fits)

    from devlab_dask import gpu_cluster

    print(f"Creating Dask cluster {name}: 0 to {n_workers} GPU workers, {gpu_memory_gib} GiB GPU memory each",
          flush=True)
    with gpu_cluster(name, n_workers=n_workers, gpu_memory_gib=gpu_memory_gib, gpu_shares=gpu_shares,
                     unknown_task_duration="5m",
                     # XGBoost and LightGBM allocate GPU memory themselves, not through RMM
                     rmm_pool=False) as cluster, Client(cluster) as client:
        submitted = time.time()
        results = run(client, fits, *task_args)
    return report(results, submitted, fits)


def report(results, submitted, fits):
    print(summary(results, submitted))
    if len(results) == fits:
        print(f"PASS: all {fits} fits completed")
        return 0
    print(f"FAIL: {len(results)} of {fits} fits completed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
