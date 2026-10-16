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
| Dagster UI and jobs that run on these clusters | `devlab addon enable dagster`, code in `config/dask/dagster/` |

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

Added for this setup: `rmm-cu12==26.2.0` (the worker memory pool; same RAPIDS release as dask-cuda 26.2), `dask-kubernetes==2026.3.0` (`KubeCluster`, for clients), and Dagster 1.13.26 with `dagster-dask`, `dagster-k8s` and `dagster-postgres` 0.29.26 (the Dagster addon). bokeh, which `dagster-dask` brings in and which serves the Dask dashboard, is held at 3.9.0: 3.10 raises an error when a distributed 2026.1 scheduler shuts down. The NVIDIA CUDA wheels are held to 12.8 (`constraints.txt`) to match the A10-24Q VM's CUDA 12.8 driver; raise them together with the driver. `python/tests/test_gpu_sharing.py` fails if `requirements.txt` drifts from `dask_requirements.md`.

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

# 4. Optional: Dagster UI at http://dagster.localhost (also applies step 3)
devlab addon enable dagster
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

## Connect Existing Clients By Address

For code that already does `Client("tcp://<address>:8786")` and submits work: run one standing cluster whose scheduler stays up on the CPU node at a fixed address. Its GPU workers scale from 0 for whatever any client submits, and back to 0 when idle. The client changes only the address.

```bash
# Scheduler + DaskAutoscaler (0 to 4 workers, 5 GiB GPU each) + dashboard ingress
python3 config/dask/devlab_dask.py gpu --workers 4 --gpu-memory-gib 5 | devlab kubectl apply -n dask -f -
devlab kubectl -n dask get daskcluster,pods        # scheduler Running, no workers yet
```

| Client runs | Address |
|-------------|---------|
| On another machine, or in a container there | `tcp://<server IP>:8786` |
| On the server (host), or in a container with a published port on it | `tcp://<server IP>:8786` or `tcp://localhost:8786` |
| In a Docker container with `--network kind` | `tcp://dev-lab-control-plane:30786` |
| In a Docker container with `--network host` | `tcp://localhost:8786` |
| In a pod | `tcp://gpu-scheduler.dask:8786` |

The dashboard is at http://gpu.dask.localhost; on a headless server, go through the SSH tunnel and open http://gpu.dask.localhost:8080.

**What the client needs**:
- **No Dask settings.** GPU memory, scaling and task duration belong to the cluster (the options below).
- **A route to the scheduler.** Docker containers on the default network reach it through the server's IP, like any other machine.
- **The same Python and Dask versions** as the cluster: Python 3.12 and dask/distributed 2026.1.1, plus whatever its tasks import. The easiest way is to build the client image `FROM localhost:5000/devlab-dask-gpu:2026.1.1`, or run the client in that image, e.g. `docker run --rm --network kind -v $PWD:/app -w /app localhost:5000/devlab-dask-gpu:2026.1.1 python workload.py`.
- **Code and data the workers can reach.** Functions defined in the script the client runs are sent with the tasks. Functions imported from the client's own modules must also exist on the workers: install them in the image, or call `client.upload_file("mymodule.py")`. Workers cannot read files in the client's container; pass the data, or read it from somewhere both can reach.

Results come back through the scheduler, so very large results are slow; reduce them on the workers first. Each worker runs one task at a time (`--nthreads 1`).

Options (`python3 config/dask/devlab_dask.py --help`):

| Option | Default | Meaning |
|--------|---------|---------|
| `--workers` | 4 | Most GPU workers at once |
| `--gpu-memory-gib` | 5 | GPU memory per worker (nvidia.com/gpu shares); 2 on an 11 GB card |
| `--task-duration` | `1m` | How long the scheduler assumes a task takes until it has measured it. Anything over a few seconds starts one worker per queued task right away |
| `--rmm-pool` | off | Fixed RMM pool per worker, for code that allocates through RMM (not XGBoost) |
| `--resources` | none | Worker resources, e.g. `GPU=1`, for tasks submitted with `resources={"GPU": 1}` |
| `--node-port` | 30786 | Scheduler NodePort. Only 30786 is mapped to the host, so only one standing cluster can be reached from outside; others take `--node-port 0` and are reachable from pods only |

To change the cluster, delete it and apply it again with new options; running clients lose their connection:

```bash
devlab kubectl -n dask delete daskcluster gpu      # also removes its autoscaler and workers
devlab kubectl -n dask delete ingress gpu-dashboard
```

The host port needs `cluster/kind-config.yaml` from this version: a cluster created before it has no port 8786 mapping (`devlab cleanup && devlab bootstrap --gpu`). Without recreating, a client in a container on the `kind` network can still use `tcp://dev-lab-control-plane:30786`.

**Security: anyone who can connect to port 8786 can run any code on the GPU workers.** A Dask scheduler runs the functions its clients send and has no login, and kind publishes the port on every interface of the server. Allow only the client machines. `ufw` does not apply to ports Docker publishes; filter them in Docker's `DOCKER-USER` chain instead, e.g. to allow only 10.10.0.0/24:

```bash
sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8786 ! -s 10.10.0.0/24 -j DROP
```

The rule does not survive a reboot unless you save it (e.g. `iptables-persistent`). To keep the scheduler on this server only, set `listenAddress: 127.0.0.1` on the 30786 mapping in `cluster/kind-config.yaml` and recreate the cluster; remote clients then use an SSH tunnel (`ssh -L 8786:localhost:8786 ...`).

## Run From Dagster

`devlab addon enable dagster` installs Dagster (Helm chart `dagster/dagster`, pinned in `python/devlab.py`) in the `dask` namespace and publishes its UI through Traefik at **http://dagster.localhost**. It needs the image from Setup step 1, which includes Dagster.

To run a job: open http://dagster.localhost, then Jobs, pick the job, then Launchpad, and Launch Run. On a headless server, tunnel the server's port 80 and open http://dagster.localhost:8080 instead: `ssh -N -L 8080:localhost:80 user@gpu-server` (see "Headless server" in [GPU.md](./GPU.md), step 7).

| Job | What it does |
|-----|--------------|
| `gpu_concurrency_job` | 4 ops that train XGBoost on the GPU, each on its own worker sharing the GPU, then `check_gpu_concurrency`, which fails unless all 4 ran at the same time. Its log shows the same timeline as the sample |
| `squares_job` | `generate_data` and `compute_squares` from `dagster-dask-integration-example`: data passed between ops on Dask workers |

How a run works:

1. The daemon starts the run as a Kubernetes Job in `dask` (K8sRunLauncher), with the same image, mounts and `dask-client` service account as the code location.
2. The run uses dagster-dask's `dask_executor`. Its `kube` cluster type creates a GPU Dask cluster with `devlab_dask.gpu_cluster`: a scheduler on the CPU node and 0 GPU workers.
3. Every op becomes one Dask task. The scheduler starts one worker per op that can run, up to `n_workers`. Each worker gets `gpu_memory_gib` GiB of the time-sliced GPU and runs one op at a time.
4. Ops pass outputs through PostgreSQL (`postgres_io_manager.py`), since each op may run on a different worker.
5. The cluster is deleted when the run pod exits, or after 10 idle minutes if the run pod was killed.

The cluster shape is the executor config, editable in the Launchpad:

```yaml
execution:
  config:
    cluster:
      kube:
        n_workers: 4          # most GPU workers at once
        gpu_memory_gib: 5     # nvidia.com/gpu shares per worker; 2 on an 11 GB card
        # rmm_pool: false, host_memory: 8Gi, op_duration: 5m, idle_timeout: 600
resources:
  gpu_task_settings:
    config:
      seconds: 30             # how long each GPU op trains
```

**Your own jobs**: add ops and jobs to `config/dask/dagster/definitions.py` with `executor_def=dask_executor` and `config=cluster_config(...)`, like the two jobs there. Put any extra module next to it and list it under `devlab-dagster` in `config/dask/kustomization.yaml`. Then publish and reload:

```bash
devlab kubectl apply -k config/dask
# ~1 minute later, when the pods see the new files: Deployment > devlab-dask > Reload in the UI
```

Ops run on GPU workers in the Dask image, so they can use the pinned packages. Op outputs are pickled into PostgreSQL, so return results and summaries rather than large datasets. They are kept until `devlab addon disable dagster`, which removes the database.

| Piece | Where |
|-------|-------|
| Chart values (code location, run launcher, PostgreSQL, ingress) | `config/addons/dagster/values.yaml` |
| Jobs, executor cluster (`gpu_kube_cluster`) | `config/dask/dagster/definitions.py` |
| IO manager | `config/dask/dagster/postgres_io_manager.py` |

The chart's bundled Bitnami PostgreSQL image is no longer published, so the addon runs the official `postgres` image as its own StatefulSet.

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
devlab addon disable dagster                           # also deletes its run history and op outputs
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
| Client `OSError: Timed out trying to connect to tcp://<address>:8786` | The standing cluster is not running (`devlab kubectl -n dask get daskcluster`), a firewall blocks port 8786, or the cluster predates the 8786 host mapping (see "Connect Existing Clients By Address") |
| Client warns about mismatched versions | Run the client with the same Python and Dask versions, e.g. in the cluster image |
| Dagster code location `devlab-dask` not loading | `devlab kubectl -n dask logs deploy/dagster-dagster-user-deployments-devlab-dask`. `ErrImagePull`: run Setup step 1. `No module named 'dagster'`: the image predates the Dagster addon; rebuild it |
| Dagster ops never start, or the run pod logs `Dask Cluster resource not actioned` | Is the Dask operator running (`devlab addon enable dask-operator`)? Then see "Workers never start" above |
| Dagster op `No stored output ...` | The upstream op's output is missing from PostgreSQL, e.g. after `devlab addon disable dagster`; re-run the whole job |
| `No module named 'psycopg'` | Something opened the Dagster database without `postgresql+psycopg2` (`postgresql.postgresqlScheme` in `config/addons/dagster/values.yaml`) |
