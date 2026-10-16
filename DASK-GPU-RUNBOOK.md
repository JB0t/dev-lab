# Dask on a Time-Sliced GPU Runbook

Run a Dask scheduler and 4 Dask-CUDA workers that share one NVIDIA GPU, then run a sample workload that shows all 4 workers using the GPU at the same time.

Target: the GPU-enabled dev-lab cluster (`./devlab bootstrap --gpu`) in a VM with an NVIDIA A10 vGPU, profile **A10-24Q** (24 GB). Other GPUs work too; see [Sizing for Other GPUs](#sizing-for-other-gpus-or-worker-counts).

| File | Purpose |
|------|---------|
| `config/gpu/nvidia-device-plugin-values.yaml` | Time slicing: each GPU becomes 4 `nvidia.com/gpu` shares |
| `config/dask/` | Namespace, scheduler, 4 GPU workers (`kubectl apply -k`) |
| `config/dask/sample/` | Job that runs `gpu_concurrency.py` against the scheduler |

## Read This First: GPU Memory Is Not Isolated

The A10 has no MIG, so the 4 workers share it through **time slicing**. Time slicing shares GPU compute only:

- Every worker sees the whole 24 GB GPU. Kubernetes **cannot** give a worker a "4 GiB slice" or enforce any GPU memory limit.
- One worker can use all the GPU memory, and the other workers then fail with out-of-memory errors.
- A GPU fault in one worker can affect the others.

So each worker limits its own memory, in `config/dask/workers.yaml`:

| Flag | Value | Effect |
|------|-------|--------|
| `--rmm-pool-size` / `--rmm-maximum-pool-size` | `4.5GiB` | Fixed RMM pool, reserved at startup. RMM allocations beyond it fail inside that worker only |
| `--set-rmm-allocator-for-libs` | `cupy` | CuPy allocates from the RMM pool, so CuPy counts against the limit |
| `--device-memory-limit` | `4GiB` | Dask spills data to host memory above 4 GiB, before the pool is full |

Budget on an A10-24Q: 4 × 4.5 GiB pools = 18 GiB. Each worker also has a CUDA context (~0.3–0.5 GiB), and the vGPU reserves some memory. That leaves about 2 GiB of headroom of the ~22 GiB `nvidia-smi` reports.

These limits only cover memory allocated through RMM. Libraries that allocate GPU memory themselves bypass them, e.g. PyTorch without RMM or raw CUDA. Keep such code inside the per-worker budget yourself.

Do not drop `--device-memory-limit`. Its default is 80% of the *whole* GPU per worker (~19 GB), which four workers on one GPU would oversubscribe.

## Prerequisites

1. A GPU-enabled dev-lab cluster: `./devlab bootstrap --gpu`. For a vGPU VM, see "vGPU Guests" in [README.md](./README.md#vgpu-guests-eg-a10-24q). The vGPU must be **licensed**: an unlicensed vGPU is throttled after 20 minutes.
2. Time slicing on with 4 shares (the default). Check that the GPU worker advertises 4:

   ```bash
   ./devlab status        # dev-lab-worker  Ready  worker  4
   ```

3. Disk space for the RAPIDS image `rapidsai/base:26.08-cuda12-py3.12`. It is about 6 GB compressed and larger once unpacked. It needs a guest driver with CUDA 12 support, i.e. vGPU 16 (R535) or newer.

## 1. Preload the Image (Recommended)

All Dask pods run on the GPU node, so only that node needs the image. Pulling it once on the VM and loading it is easier to watch than a 6 GB pull inside the node:

```bash
docker pull rapidsai/base:26.08-cuda12-py3.12
kind load docker-image rapidsai/base:26.08-cuda12-py3.12 --name dev-lab --nodes dev-lab-worker
```

Skip this step and the node pulls the image itself. Pods then stay in `ContainerCreating` for several minutes.

## 2. Deploy the Scheduler and Workers

```bash
./devlab kubectl -- apply -k config/dask
./devlab kubectl -- -n dask rollout status deployment/dask-scheduler --timeout=20m
./devlab kubectl -- -n dask rollout status deployment/dask-cuda-worker --timeout=20m
./devlab kubectl -- -n dask get pods -o wide
```

Expected: 1 `dask-scheduler` and 4 `dask-cuda-worker` pods, all `Running` on `dev-lab-worker`. The 4 workers share the same GPU.

Check the memory limits on the VM (not inside a pod):

```bash
nvidia-smi
```

The memory usage is about 4 × (4.5 GiB pool + CUDA context), roughly 19–20 GiB. Each worker reserves its pool at startup, so this shows before any work runs. Four `python` processes are listed. Inside a container the process list can be empty because of PID namespaces.

## 3. Run the Sample Workload

The sample Job connects to the scheduler and pins one task to each worker. Each task runs CuPy matrix multiplies for 30 seconds and records when it ran:

```bash
./devlab kubectl -- apply -k config/dask/sample
./devlab kubectl -- -n dask wait --for=condition=complete job/gpu-concurrency --timeout=15m
./devlab kubectl -- -n dask logs job/gpu-concurrency
```

While it runs, `watch -n1 nvidia-smi` on the VM shows GPU utilization near 100% with all 4 worker processes.

Expected output (names and numbers vary):

```text
Connecting to tcp://dask-scheduler:8786, waiting for 4 workers...
Running a 30s GPU task on each worker...
worker                                   gpu                                           start    end  iters  memory resource
dask-cuda-worker-7d9f8c6b5-2xkqp         GPU-4cf8db2d-06c0-7d70-1a51-e59b25b2c16c       0.0s  30.1s    212  PoolMemoryResource
dask-cuda-worker-7d9f8c6b5-8fz4t         GPU-4cf8db2d-06c0-7d70-1a51-e59b25b2c16c       0.1s  30.2s    208  PoolMemoryResource
dask-cuda-worker-7d9f8c6b5-hm9wd         GPU-4cf8db2d-06c0-7d70-1a51-e59b25b2c16c       0.1s  30.2s    210  PoolMemoryResource
dask-cuda-worker-7d9f8c6b5-qs7lv         GPU-4cf8db2d-06c0-7d70-1a51-e59b25b2c16c       0.2s  30.3s    209  PoolMemoryResource
PASS: all 4 tasks were running at the same time for 29.9s
```

How to read it:

- **4 different workers, 1 GPU UUID**: each task ran in its own worker on a time-sliced share of the same physical GPU.
- **Overlapping start/end**: all 4 were on the GPU at once. Each gets about a quarter of the GPU time, so a task finishes about a quarter of the iterations it would finish alone.
- **`PoolMemoryResource`** (or a wrapper around it): the worker allocates from its fixed RMM pool.

The Job exits non-zero and prints `FAIL:` when the tasks did not overlap or fewer than 4 workers ran them.

To run it again (Jobs cannot be re-applied while the old one exists):

```bash
./devlab kubectl -- -n dask delete job gpu-concurrency
./devlab kubectl -- apply -k config/dask/sample
```

Optional settings, as env vars in `config/dask/sample/job.yaml`: `TASK_SECONDS` (default 30) and `MATRIX_SIZE` (default 4096, ~64 MiB per matrix).

## 4. Use It for Your Own Work

Run your Dask client in the cluster with the **same image**. Client, scheduler and workers must have matching Dask versions. Copy `config/dask/sample/` as a starting point and connect with `Client("tcp://dask-scheduler:8786")`. Keep each task's GPU memory within its worker's 4.5 GiB pool.

## Sizing for Other GPUs or Worker Counts

Per-worker RMM pool ≈ (GPU memory reported by `nvidia-smi` − ~0.5 GiB per worker for CUDA context − ~1 GiB headroom) ÷ workers. Set `--device-memory-limit` about 0.5 GiB below the pool.

| GPU (as seen by the VM) | Workers | `--rmm-pool-size` / `--rmm-maximum-pool-size` | `--device-memory-limit` |
|-------------------------|---------|----------------------------------------------|-------------------------|
| A10-24Q (~22 GiB) | 4 | `4.5GiB` | `4GiB` |
| A10-24Q (~22 GiB) | 2 | `9GiB` | `8.5GiB` |
| 16 GB GPU (~15 GiB) | 4 | `3GiB` | `2.5GiB` |

To change the worker count, keep these equal to each other:

1. `replicas` in `config/gpu/nvidia-device-plugin-values.yaml`, then `./devlab gpu-plugin`
2. `replicas` in `config/dask/workers.yaml`, and the pool flags from the table
3. `EXPECTED_WORKERS` in `config/dask/sample/job.yaml`

Then `./devlab kubectl -- apply -k config/dask`. `python/tests/test_gpu_sharing.py` checks that these numbers match and that the pools fit in an A10-24Q.

## Clean Up

```bash
./devlab kubectl -- delete -k config/dask/sample
./devlab kubectl -- delete -k config/dask
```

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| Workers `Pending`, event `Insufficient nvidia.com/gpu` | Fewer than 4 free shares. Check `./devlab status` and other pods using GPUs; is time slicing on? |
| Worker fails with `UnexpectedAdmissionError` | It requests more than 1 `nvidia.com/gpu`; with time slicing each worker takes exactly 1 |
| Worker crash-loops with RMM / `out_of_memory` at startup | Pools don't fit: other GPU processes are using memory, or the pool is too large for the GPU. Lower the pool size |
| `MemoryError` / `out_of_memory` in a task | The task needs more than its 4.5 GiB pool. Use smaller partitions, or fewer workers with larger pools |
| `requirement error: unsatisfied condition: cuda>=12.9` | Guest driver too old for the image. Use vGPU 16 (R535) or newer, or an older RAPIDS image |
| Everything slows down after ~20 minutes | vGPU not licensed: `nvidia-smi -q \| grep -i 'license status'` |
| Sample Job waits forever at "waiting for 4 workers" | Workers not running or can't reach `dask-scheduler:8786`. Check `./devlab kubectl -- -n dask logs deployment/dask-cuda-worker` |
| Pods stuck in `ContainerCreating` | Still pulling the ~6 GB image; preload it (step 1) |
