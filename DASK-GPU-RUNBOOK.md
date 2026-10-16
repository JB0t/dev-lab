# Dask GPU Clusters Runbook

Dask clusters whose GPU workers scale from 0: the client says how many workers it may use and how much GPU memory each gets, and the scheduler starts workers for the tasks it receives and removes them when idle. Workers time-share the GPU; the scheduler runs on a CPU node.

Target: the GPU-enabled dev-lab cluster (`devlab bootstrap --gpu`, see [GPU.md](./GPU.md)), first on one node with an NVIDIA A10-24Q (24 GB, CUDA 12.8 guest driver). The same setup scales to more GPU nodes.

## How It Works

```text
client ──creates──► DaskCluster (scheduler on a CPU node, 0 GPU workers)
       ──submits tasks──► scheduler ── adaptive target ──► DaskAutoscaler (Dask Kubernetes Operator)
                                                             └─► scales GPU workers 0 ↔ n_workers
GPU node (tainted nvidia.com/gpu): workers, each requesting gpu_memory_gib nvidia.com/gpu shares
```

| Piece | Where |
|-------|-------|
| Dask Kubernetes Operator | `devlab addon enable dask-operator` (chart pinned in `python/devlab.py`) |
| Client helper `gpu_cluster()` | `config/dask/devlab_dask.py` |
| Image for scheduler, workers and clients | `config/dask/image/` (from the pinned versions in `dask_requirements.md`) |
| Namespace `dask`, client RBAC, helper ConfigMap | `config/dask/` (`kubectl apply -k`) |
| Sample client job | `config/dask/sample/` |

- **Scale from 0**: `gpu_cluster(..., n_workers=4)` creates the cluster with no workers and a `DaskAutoscaler` with minimum 0, maximum 4. The operator asks the scheduler every few seconds how many workers its queued tasks need (Dask's adaptive target) and starts or removes worker pods within that range. Idle workers are removed (at most a quarter of them per step).
- **GPU memory per worker**: each GPU node advertises one `nvidia.com/gpu` share per GiB of GPU memory (22 on an A10-24Q). A worker with `gpu_memory_gib=5` requests 5 shares, so Kubernetes only starts it on a GPU node with 5 GiB free. By default it also limits itself to a fixed 4.5 GiB RMM pool (5 GiB minus its CUDA context), spilling Dask data to host memory above 4 GiB. Only memory allocated through RMM comes from that pool. XGBoost allocates its own GPU memory, so run XGBoost workers with `rmm_pool=False`; otherwise the pool holds memory XGBoost cannot use. Workers of different sizes and from different clusters share a GPU this way.
- **Placement**: GPU nodes are tainted; workers tolerate the taint and select `devlab.io/gpu=true`. The scheduler and clients select `devlab.io/gpu=false`, so they run on the CPU worker.

**GPU memory is not isolated.** Time slicing shares compute; every worker sees the whole GPU. The shares only make Kubernetes count GPU memory, and the RMM pool only limits memory allocated through RMM. A library with its own CUDA allocator, such as XGBoost, can use more than its worker requested and starve the others, so size `gpu_memory_gib` for its peak use.

## Versions

One image (`config/dask/image/`) runs the scheduler, the workers and in-cluster clients, so all sides have the same versions. It is built from the versions in `dask_requirements.md`:

| Package | Version |
|---------|---------|
| Python | 3.12.12 |
| dask, distributed | 2026.1.1 |
| dask-cuda | 26.2.0 |
| numpy, pandas, pyarrow | 2.4.5, 2.3.3, 23.0.1 |
| lightgbm, xgboost, falcata | 4.7.0, 3.2.0, 1.0.5 |
| numba, numba-cuda | 0.67.0, 0.22.2 |

Added for this setup: `rmm-cu12==26.2.0` (the worker memory pool; same RAPIDS release as dask-cuda 26.2) and `dask-kubernetes==2026.3.0` (`KubeCluster`, for clients). The NVIDIA CUDA wheels are held to 12.8 (`constraints.txt`) to match the A10-24Q VM's CUDA 12.8 driver; raise them together with the driver. `python/tests/test_gpu_sharing.py` fails if `requirements.txt` drifts from `dask_requirements.md`.

**`numba.cuda` cannot be imported with these versions.** numba-cuda 0.22.2 (the newest dask-cuda 26.2 accepts) does not support numba 0.67 (`module 'numba.cuda.types' has no attribute 'NPDatetime'`) or numpy 2.4 (`np.trapz` was removed). CPU numba works, and so do Dask-CUDA workers: dask-cuda 26.2 only imports `numba.cuda` for GPUDirect Storage spilling. The sample therefore uses XGBoost for its GPU work. numba-cuda 0.30.4 works with numba 0.67 and numpy 2.4.5, but needs dask-cuda 26.4 or later.

## Setup

Once per cluster, after `devlab bootstrap --gpu`:

```bash
# 1. Build the image into the local registry (~10 minutes, 2.5 GB). Registry
#    data survives a cluster recreate, so this is needed again only when the
#    image changes.
devlab build -t devlab-dask-gpu:2026.1.1 --push config/dask/image

# 2. Install the Dask Kubernetes Operator
devlab addon enable dask-operator

# 3. Namespace, client service account and the devlab_dask helper
devlab kubectl apply -k config/dask
```

The cluster needs at least one CPU-only worker for the scheduler (the default `cluster/gpu-workers.yaml` has one).

## Run the Sample

The sample client (`config/dask/sample/gpu_concurrency.py`) creates a cluster with 0 workers (`rmm_pool=False`), submits 4 tasks that each train XGBoost models on the GPU (`device="cuda"`), and checks that the scheduler scaled to 4 workers that used the GPU at the same time:

```bash
devlab kubectl apply -k config/dask/sample
devlab kubectl -n dask get pods -w          # scheduler, then 4 workers appear; Ctrl-C to stop watching
devlab kubectl -n dask logs -f job/gpu-concurrency
```

Expected output (names and numbers vary):

```text
Creating Dask cluster gpu-concurrency: 0 to 4 GPU workers, 5 GiB GPU memory each
Scheduler up with 0 workers; submitting 4 GPU tasks...
worker                                        joined  start    end rounds
gpu-concurrency-default-worker-1f2e3d4c5b      14.2s  31.0s  61.1s    410
gpu-concurrency-default-worker-6a7b8c9d0e      15.0s  31.0s  61.2s    400
gpu-concurrency-default-worker-a1b2c3d4e5      15.3s  31.0s  61.2s    410
gpu-concurrency-default-worker-f6e5d4c3b2      30.9s  31.0s  61.3s    400
GPU(s): GPU-4cf8db2d-06c0-7d70-1a51-e59b25b2c16c
Scale-up: 31.0s from submitting the tasks to all workers running them
PASS: all 4 tasks were running at the same time for 30.1s
```

- **4 workers, 1 GPU UUID**: four workers on time-sliced shares of the same GPU.
- **Scale-up**: from 0 workers to all 4 running. The first run is slower while the GPU node pulls the image.
- **Overlapping start/end**: the tasks ran at once; each gets about a quarter of the GPU time.
- **rounds**: XGBoost boosting rounds each task trained.

The cluster is deleted when the job ends. Settings are env vars in `config/dask/sample/job.yaml`: `N_WORKERS` (4), `GPU_MEMORY_GIB` (5; use 2 on an 11 GB card), `TASK_SECONDS` (30). Jobs cannot be re-applied while the old one exists:

```bash
devlab kubectl -n dask delete job gpu-concurrency
devlab kubectl apply -k config/dask/sample
```

## Use It From Your Own Code

```python
from dask.distributed import Client
from devlab_dask import gpu_cluster

# Up to 4 workers with 5 GiB of GPU memory each, scaling from 0
with gpu_cluster("training", n_workers=4, gpu_memory_gib=5, rmm_pool=False,
                 task_durations={"train_model": "2m"}) as cluster, Client(cluster) as client:
    futures = client.map(train_model, partitions)
    results = client.gather(futures)
```

| Argument | Meaning |
|----------|---------|
| `name` | DaskCluster name, unique in the namespace |
| `n_workers` | Most workers the scheduler may start (it starts from 0) |
| `gpu_memory_gib` | GPU memory per worker: its `nvidia.com/gpu` shares and RMM pool |
| `rmm_pool` | Give each worker a fixed RMM pool of its GPU memory (default `True`). Use `False` for XGBoost and other code that does not allocate through RMM |
| `task_durations` | How long tasks of a function take, e.g. `{"train_model": "2m"}`. Dask's adaptive target assumes unknown tasks take 0.5 s, so without this it first asks for 1 worker and adds more once tasks have finished and their real duration is known. With it, the scheduler asks for enough workers at once. |
| `worker_resources` | Dask worker resources, e.g. `{"GPU": 1}`; tasks submitted with `resources={"GPU": 1}` then run one per worker |
| `host_memory` | Host memory limit per worker pod (default `8Gi`) |
| `namespace` | Kubernetes namespace (default: the current one) |

Clusters with different sizes can run side by side, e.g. `gpu_cluster("a", n_workers=2, gpu_memory_gib=8)` and `gpu_cluster("b", n_workers=3, gpu_memory_gib=2)` share 22 shares on an A10-24Q. Workers that do not fit wait in `Pending` until shares free up.

**In the cluster** (recommended): run the client as a pod in the `dask` namespace like `config/dask/sample/job.yaml`: service account `dask-client`, the same image, `PYTHONPATH=/devlab` with the `devlab-dask` ConfigMap mounted at `/devlab`, and `nodeSelector: devlab.io/gpu: "false"`.

**From your machine**: install the same versions (`pip install -r config/dask/image/requirements.txt -c config/dask/image/constraints.txt`, or at least the same Python, `dask`, `distributed` and `dask-kubernetes`), put `config/dask` on `PYTHONPATH`, and point `KUBECONFIG` at the dev-lab cluster. `KubeCluster` reaches the scheduler through a port-forward. Mismatched Dask versions between client and cluster cause errors.

## Sizing

Shares per GPU = GPU memory in whole GiB (`devlab status`, GPUs column). Each worker also needs about 0.5 GiB for its CUDA context, which comes out of its own shares.

| GPU | Shares | Example layouts |
|-----|--------|-----------------|
| A10-24Q (24 GB) | 22 | 4 × 5 GiB, 2 × 10 GiB, 2 × 8 + 3 × 2 GiB |
| 11 GB card (test) | 10 | 4 × 2 GiB, 2 × 4 GiB |

**More GPU nodes**: add GPU workers to `cluster/gpu-workers.yaml`, one GPU per worker node (`devices: 0`, `devices: 1`, ...), and recreate the cluster. Each node advertises its own shares and workers start on any node with enough free; nothing else changes.

## Clean Up

```bash
devlab kubectl -n dask delete daskclusters --all       # clusters left by clients that did not close them
devlab addon disable dask-operator
devlab kubectl delete -k config/dask
```

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| Workers `Pending`, event `Insufficient nvidia.com/gpu` | Not enough free GPU memory (shares) for `gpu_memory_gib` on any GPU node. Use smaller workers or fewer, or wait for others to finish |
| Scheduler `Pending` | No CPU-only node (`devlab.io/gpu=false`) without a taint; keep a CPU worker in `cluster/gpu-workers.yaml` |
| Workers never start | Check the operator: `devlab kubectl -n dask-operator logs deploy/dask-kubernetes-operator`. `Unable to get desired number of workers` means the scheduler's `/api/v1/adaptive_target` is unreachable |
| Only 1 worker starts for many tasks | Dask does not know the tasks are long yet; pass `task_durations` |
| `ErrImagePull` for `localhost:5000/devlab-dask-gpu` | Image not in the local registry; run step 1 of Setup |
| `out_of_memory` / `MemoryError` in a task | The task needs more GPU memory than its worker's pool; raise `gpu_memory_gib` |
| XGBoost `cudaErrorMemoryAllocation` / out of memory | Other workers' RMM pools or XGBoost use hold the GPU memory; use `rmm_pool=False` for XGBoost workers and size `gpu_memory_gib` for their peak use |
| `module 'numba.cuda.types' has no attribute 'NPDatetime'` | `numba.cuda` does not work with the pinned versions; see Versions |
| `CUDA-capable device(s) is/are busy or unavailable` | GPU compute mode is not Default (see GPU.md, step 3) |
| Client `ModuleNotFoundError: devlab_dask` | Mount the `devlab-dask` ConfigMap and set `PYTHONPATH`, as in `config/dask/sample/job.yaml` |
