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
- **Placement**: GPU nodes are tainted; workers tolerate the taint and select `devlab.io/gpu=true`. The scheduler, clients and Dagster's PostgreSQL select `devlab.io/gpu=false`, so they run on the CPU worker.

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

The cluster is deleted when the job ends. Settings are env vars in `config/dask/sample/job.yaml`: `N_WORKERS` (4), `GPU_MEMORY_GIB` (5; use 2 on an 11 GB card), `GPU_SHARES` (unset: one per GiB; 1 with MPS), `TASK_SECONDS` (30). Jobs cannot be re-applied while the old one exists:

```bash
devlab kubectl -n dask delete job gpu-concurrency
devlab kubectl apply -k config/dask/sample
```

## Stress Test: A Grid Of Fits

`config/dask/sample/gpu_stress.py` is the GPU sample's heavier sibling, shaped like a model-fitting job: `FITS` XGBoost models with different hyper-parameters (a small grid) are trained on synthetic data, one per worker at a time, each with a validation set. The data (`ROWS` x `COLUMNS`, 2 M x 64 by default) and trees (`MAX_DEPTH` 10, `ROUNDS` 200) are big enough that a fit keeps its GPU share busy with long kernels. The result to compare is the total **rounds/s**:

```bash
# Against the standing cluster, from the server or any client machine; the client needs only dask and distributed
run() { docker run --rm -e SCHEDULER_ADDRESS=tcp://<server IP>:8786 "$@" \
  -v "$PWD/config/dask/sample:/s:ro" python:3.12.12-slim-bookworm sh -c \
  'pip install -q dask==2026.1.1 distributed==2026.1.1 && python /s/gpu_stress.py'; }
run -e N_WORKERS=1 -e FITS=2     # the GPU alone: one fit at a time
run -e N_WORKERS=4 -e FITS=8     # four at once
run -e N_WORKERS=4 -e FITS=8 -e DATASETS=8   # every fit on its own data, built every time
nvidia-smi dmon -s um            # on the server meanwhile: GPU utilisation and memory
```

Like a grid search, the fits share `DATASETS` datasets (1 by default; fit `i` uses dataset `i % DATASETS`). A worker keeps the dataset of its last fit on the GPU, so the next fit on the same data skips building it: the `build` column shows the quantile sketch and the copy to the GPU, or `cached`. This is how a fitting job should use its GPU memory share: hold the data it trains on, not leave it idle, because a fit's own memory is small (the QuantileDMatrix stores 8-bit bins, about 1.5 GiB for the defaults) and the GPU's compute, not its memory, limits the throughput. The cache lasts one run (`CACHE=run`, the default): standing workers outlive a run, so every run starts by building its data, and runs at different worker counts compare fairly. `CACHE=off` builds the data for every fit; `CACHE=keep` also reuses data an earlier run left behind. `rounds/s` per fit counts the training only; the `Throughput` line counts the builds too, so it shows what the cache saves. On the A10-24Q with two workers and eight fits: 22.5 rounds/s building every time (`DATASETS=8`), 29 rounds/s with one dataset cached for six of the eight fits, 1.3x from the same GPU work.

With time slicing the four-worker run's rounds/s stays about the one-worker run's (the workers take turns). With MPS it grows until the GPU is full; on an A10-24Q the small sample scaled 3.7x (GPU.md, "MPS Instead of Time Slicing"), and this one scaled 2.0x at the defaults: 11.3 rounds/s with `N_WORKERS=1 FITS=2`, 21.7 rounds/s with `N_WORKERS=2 FITS=4`, 22.7 rounds/s with `N_WORKERS=4 FITS=8`. One heavy fit alone already keeps about half the GPU busy, so the four-worker run fills the rest and no more. `N_WORKERS` is how many fits run at once: the client submits that many and the next as one finishes, so a standing cluster scales to `N_WORKERS` workers rather than its `--workers` maximum. With four workers, `FITS=8` gives each two fits in a row. Workers already up beyond `N_WORKERS` (a DaskAutoscaler minimum, `gpu_warm.py --dask-autoscaler`) stay idle and the client says so; warm with `--nodes` only, or `down` first, when comparing worker counts with `gpu_metrics.py`. Bigger `ROWS` or `MAX_DEPTH` make each fit heavier; `GPU_MEMORY_GIB` must hold the data (the default fits 5 GiB). `LIBRARY=lightgbm` needs an image with LightGBM built with CUDA (the pip wheel is CPU-only).

In the cluster instead: `devlab kubectl apply -k config/dask/sample` (the ConfigMap with both scripts), then `devlab kubectl apply -f config/dask/sample/stress-job.yaml` and `devlab kubectl -n dask logs -f job/gpu-stress`. It creates its own cluster unless `SCHEDULER_ADDRESS` is set in the manifest; re-runs need `devlab kubectl -n dask delete job gpu-stress` first.

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
| `gpu_shares` | `nvidia.com/gpu` shares per worker when not one per GiB: `1` with MPS (GPU.md, "MPS Instead of Time Slicing") |
| `rmm_pool` | Give each worker a fixed RMM pool of its GPU memory (default `True`). Use `False` for XGBoost and other code that does not allocate through RMM |
| `task_durations` | How long tasks of a function take, e.g. `{"train_model": "2m"}`. Dask's adaptive target assumes unknown tasks take 0.5 s, so without this it first asks for 1 worker and adds more once tasks have finished and their real duration is known. With it, the scheduler asks for enough workers at once. |
| `worker_resources` | Dask worker resources (default `{"GPU": 1}`; `{}` for none). Tasks submitted with `resources={"GPU": 1}` run only on workers that declare it, one per worker |
| `host_memory` | Host memory limit per worker pod (default `8Gi`) |
| `namespace` | Kubernetes namespace (default: the current one) |
| `worker_env`, `worker_env_from`, `worker_volumes`, `worker_volume_mounts` | Environment variables and files for the workers; see [Worker Environment](#worker-environment) |

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

**Check it from the client machine** with the GPU sample in address mode. The client needs only Python 3.12 with dask and distributed 2026.1.1; the GPU work runs on the workers:

```bash
docker run --rm -e SCHEDULER_ADDRESS=tcp://<server IP>:8786 -e N_WORKERS=4 \
  -v "$PWD/config/dask/sample:/s:ro" python:3.12.12-slim-bookworm sh -c \
  'pip install -q dask==2026.1.1 distributed==2026.1.1 && python /s/gpu_concurrency.py'
# Scheduler has 0 workers; submitting 4 GPU tasks...
# ... 4 workers, 1 GPU UUID ...
# PASS: all 4 tasks were running at the same time for ...
```

`N_WORKERS` must not exceed the cluster's `--workers`. Use `TASK_SECONDS` to make the tasks longer or shorter.

**Dashboard**: http://<server IP>:8787/workers (also `/status`, `/tasks`, `/graph`), or http://gpu.dask.localhost/workers through Traefik on the server or the SSH tunnel (http://gpu.dask.localhost:8080/workers). Workers appear there as the scheduler starts them.

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
| `--gpu-memory-gib` | 5 | GPU memory per worker in GiB (with time slicing also its nvidia.com/gpu shares); 2 on an 11 GB card |
| `--gpu-shares` | same as `--gpu-memory-gib` | nvidia.com/gpu shares per worker when not one per GiB: `1` with MPS (GPU.md, "MPS Instead of Time Slicing") |
| `--task-duration` | `1m` | How long the scheduler assumes a task takes until it has measured it. Anything over a few seconds starts one worker per queued task right away |
| `--rmm-pool` | off | Fixed RMM pool per worker, for code that allocates through RMM (not XGBoost) |
| `--resources` | `GPU=1` | Worker resources for tasks submitted with `resources={"GPU": 1}`, comma-separated `NAME=AMOUNT`; `none` for none. A task that asks for a resource no worker declares never runs, so the names must match the client's (case-sensitive). Workers still scale from 0: they declare the resources when they start |
| `--node-port` | 30786 | Scheduler NodePort. Only 30786 is mapped to the host (port 8786), so only one standing cluster can be reached from outside; others take `--node-port 0` and are reachable from pods only |
| `--dashboard-node-port` | 30787 | Dashboard NodePort, mapped to host port 8787 |

To change the cluster, delete it and apply it again with new options; running clients lose their connection:

```bash
devlab kubectl -n dask delete daskcluster gpu      # also removes its autoscaler and workers
devlab kubectl -n dask delete ingress gpu-dashboard
```

The host ports need `cluster/kind-config.yaml` from this version: a cluster created before it has no port 8786 and 8787 mappings (`devlab cleanup && devlab bootstrap --gpu`). Without recreating, a client in a container on the `kind` network can still use `tcp://dev-lab-control-plane:30786`.

**Security: anyone who can connect to port 8786 can run any code on the GPU workers.** A Dask scheduler runs the functions its clients send and has no login, and kind publishes the port on every interface of the server. Allow only the client machines. `ufw` does not apply to ports Docker publishes; filter them in Docker's `DOCKER-USER` chain instead, e.g. to allow only 10.10.0.0/24:

```bash
sudo iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8786 ! -s 10.10.0.0/24 -j DROP
```

The rule does not survive a reboot unless you save it (e.g. `iptables-persistent`). To keep the scheduler on this server only, set `listenAddress: 127.0.0.1` on the 30786 mapping in `cluster/kind-config.yaml` and recreate the cluster; remote clients then use an SSH tunnel (`ssh -L 8786:localhost:8786 ...`).

## Worker Environment

Workers get files and environment variables from Kubernetes objects in the `dask` namespace, not from the host: a Secret for files such as credentials (the equivalent of a compose bind mount like `/etc/secret:/etc/secret`), a ConfigMap for environment variables. Both `gpu_cluster` and the standing cluster take them as `gpu_cluster_spec` options:

| Option | Kubernetes field on the worker | Example |
|--------|--------------------------------|---------|
| `worker_volumes` | `volumes` | `[{"name": "host-secret", "secret": {"secretName": "host-secret"}}]` |
| `worker_volume_mounts` | `volumeMounts` | `[{"name": "host-secret", "mountPath": "/etc/secret", "readOnly": True}]` |
| `worker_env_from` | `envFrom` (every key as a variable) | `[{"configMapRef": {"name": "worker-env"}}]` |
| `worker_env` | `env` (single variables) | `[{"name": "LOG_LEVEL", "value": "info"}]` |

**A host folder as files on every worker.** `devlab kubectl` runs in a container that cannot see `/etc`, so build the Secret on the host and pipe it in. Each file directly in the folder becomes one key; run it again after the folder changes:

```bash
sudo python3 - /etc/secret <<'PY' | devlab kubectl -n dask apply -f -
import base64, json, os, sys
root = sys.argv[1]
data = {}
for name in sorted(os.listdir(root)):
    path = os.path.join(root, name)
    if os.path.isfile(path):
        with open(path, "rb") as f:
            data[name] = base64.b64encode(f.read()).decode()
json.dump({"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
           "metadata": {"name": "host-secret"}, "data": data}, sys.stdout)
PY
```

Subfolders are skipped, file names may contain only letters, digits, `-`, `_` and `.`, and a Secret holds at most 1 MiB. Mounted without `subPath`, the files appear under `/etc/secret/` and running workers see changes within about a minute.

**Environment variables from a ConfigMap.** Write them as `KEY=value` lines (an env file, like compose's `env_file`) and create or update the ConfigMap:

```bash
devlab kubectl -n dask create configmap worker-env --from-env-file=/dev/stdin \
    --dry-run=client -o yaml < worker.env | devlab kubectl apply -n dask -f -
```

Variables are read when a worker starts, so after a change only new workers have them; idle workers scale to 0, or delete the worker pods to restart them now. Use a Secret with `{"secretRef": {"name": ...}}` in `worker_env_from` for values that are secret.

**Standing cluster with both.** The command line has no options for these, so generate its manifests from Python (from the repo root; delete the old cluster first, see above):

```bash
python3 - <<'PY' | devlab kubectl apply -n dask -f -
import json, sys
sys.path.insert(0, "config/dask")
from devlab_dask import standing_cluster_manifests, STANDING_SCHEDULER_NODE_PORT, STANDING_DASHBOARD_NODE_PORT
items = standing_cluster_manifests(
    "gpu", 4, 5,                         # --workers, --gpu-memory-gib
    rmm_pool=False,                      # the command line's defaults
    unknown_task_duration="1m",
    scheduler_node_port=STANDING_SCHEDULER_NODE_PORT,
    dashboard_node_port=STANDING_DASHBOARD_NODE_PORT,
    worker_volumes=[{"name": "host-secret", "secret": {"secretName": "host-secret"}}],
    worker_volume_mounts=[{"name": "host-secret", "mountPath": "/etc/secret", "readOnly": True}],
    worker_env_from=[{"configMapRef": {"name": "worker-env"}}],
)
json.dump({"apiVersion": "v1", "kind": "List", "items": items}, sys.stdout)
PY
```

Add `image="localhost:5000/<image>"` for another image. With `gpu_cluster`, pass the same `worker_*` arguments. Workers do not start while a Secret or ConfigMap they use is missing (`CreateContainerConfigError`). Check a worker with `devlab kubectl -n dask exec <worker pod> -- sh -c 'ls -l /etc/secret; env | sort'`.

Anyone who can submit tasks to the scheduler can read these files and variables on the workers; see the security note above.

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

## On Another Cluster: One Worker Per GPU Node (AKS, EKS)

The lab shares one GPU between workers because it has one GPU. A cloud pool of single-GPU nodes (Azure `Standard_NC4as_T4_v3`: one T4 16 GB, 4 vCPUs, 28 GB; AWS `g4dn.xlarge` the same card) wants the opposite: no sharing, one worker per node, each holding the whole card, and the node count following the queue.

`devlab addon enable dask-operator` and `devlab kubectl` only ever talk to the lab's kind cluster (Helm and kubectl run in containers with its kubeconfig). On another cluster the same two steps are your own helm and kubectl against your context:

```bash
kubectl config use-context my-aks
helm repo add dask https://helm.dask.org && helm repo update
helm upgrade --install dask-kubernetes-operator dask/dask-kubernetes-operator \
  --version 2026.3.0 --namespace dask-operator --create-namespace --wait \   # the version pinned in python/devlab.py
  --set-json 'tolerations=[{"operator":"Exists"}]' --set nodeSelector.agentpool=system
                                  # on a cluster whose pools are all tainted the operator pod is Pending
                                  # without a toleration; the chart's tolerations/nodeSelector values place it
kubectl apply -k config/dask      # namespace dask, client RBAC, the devlab-dask ConfigMap. -k, not -f:
                                  # -f on the directory tries to apply kustomization.yaml as a resource
                                  # ("no matches for kind Kustomization in version kustomize.config.k8s.io/v1beta1")
```

Then the manifests, which are the same as the lab's with the placement options:

```bash
python3 config/dask/devlab_dask.py gpu --workers 8 \
  --gpu-memory-gib 15 --gpu-shares 1 --rmm-pool \
  --host-memory 20Gi --worker-cpu 3 --one-worker-per-node --runtime-class none --node-port 0 --ingress-class none \
  --worker-node-selector agentpool=t4 --worker-toleration sku=gpu:NoSchedule \
  --scheduler-node-selector agentpool=system --scheduler-toleration CriticalAddonsOnly:NoSchedule \
  --image myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1 \
  | kubectl apply -n dask -f -
```

| Option | Why here |
|---|---|
| `--gpu-shares 1 --gpu-memory-gib 15` | A whole T4 per worker (`nvidia.com/gpu: 1`; no sharing config on the node), 15 GiB of its 16 for the worker's spill limit and RMM pool |
| `--one-worker-per-node` | A required anti-affinity between the cluster's workers. With one GPU per node the GPU request already enforces it; the affinity keeps it true on nodes with several, and keeps two clusters from sharing a node |
| `--host-memory 20Gi --worker-cpu 3` | Most of the node: 28 GB and 4 vCPUs, with room for the kubelet and the device plugin |
| `--runtime-class none` | AKS and EKS GPU nodes run the NVIDIA runtime by default; the `nvidia` RuntimeClass exists only with the GPU Operator |
| `--worker-node-selector`, `--worker-toleration` | The pool's label (AKS: `agentpool=<name>`; EKS: `eks.amazonaws.com/nodegroup=<name>`) and its taint (set when creating the pool, e.g. `sku=gpu:NoSchedule`); a Spot pool adds `kubernetes.azure.com/scalesetpriority=spot:NoSchedule` |
| `--scheduler-node-selector`, `--scheduler-toleration` | The scheduler on the system or a CPU pool. `kubectl get nodes -L agentpool` names the pools; `kubectl get nodes -l agentpool=<pool> -o jsonpath='{.items[0].spec.taints}'` shows the taints to tolerate, one flag each (`KEY[=VALUE]:EFFECT`), or `--scheduler-toleration all` for every taint, like the operator chart above. `--worker-toleration all` likewise |
| `--node-port 0` | No NodePort: clients in the cluster use `gpu-scheduler.dask:8786`, from outside use `kubectl port-forward` |
| `--ingress-class none` | No dashboard Ingress (the lab's is for Traefik); `kubectl -n dask port-forward svc/gpu-scheduler 8787:8787` shows it. Or the cluster's class, e.g. `nginx` or `webapprouting.kubernetes.azure.com`, with the host in `standing_cluster_manifests(dashboard_host=...)` |
| `--rmm-pool` | On for RAPIDS/cuDF work; off for XGBoost, which allocates its own memory (the default) |

The same options exist on `gpu_cluster_spec`/`gpu_cluster` (`worker_node_selector`, `worker_tolerations`, `scheduler_node_selector`, `scheduler_tolerations`, `runtime_class`, `one_worker_per_node`, `worker_cpu`) for clusters created from code and from Dagster.

**The pool.** What made the lab's throughput plateau was the GPU's compute, so the pool is arranged for one fit per GPU and as many GPUs as the queue needs:

- `NC4as_T4_v3` with the cluster autoscaler, `--min-count 0 --max-count N`, Spot if the fits are restartable (Dask reruns a task whose worker is lost; an evicted node costs one fit). Taint it (`--node-taints sku=gpu:NoSchedule`) so only the workers land there, label it (`--labels agentpool` is automatic).
- One fit saturates a T4 (a third of an A10), so there is nothing to gain from MPS or time slicing here; the throughput is the node count. `--workers N` equals the pool's max count, and the DaskAutoscaler plus the cluster autoscaler scale nodes 0..N with the queue: a new node takes 3 to 5 minutes plus the image pull, so for a steady stream set the autoscaler's `minimum` to 1 or 2 during working hours, or `--task-duration` long enough that the scheduler asks for all the workers at once.
- The image: push it to ACR or ECR in the region (`devlab build` locally, then `docker push` to ACR; or the cluster registry of CLUSTER-REGISTRY-RUNBOOK.md for tests). A 2.5 GB pull per new node is part of the scale-up time; a bigger VM with several GPUs (`NC64as_T4_v3`, 4 T4s, one worker per GPU with `--gpu-shares 1` and without `--one-worker-per-node`) pulls once for four workers.
- GPU drivers and the device plugin: AKS installs the driver on GPU pools; install the NVIDIA device plugin DaemonSet (or the GPU Operator with the driver disabled) so `nvidia.com/gpu` is allocatable. EKS GPU AMIs include both.
- 4 vCPUs is the limit for the CPU side (data loading, the DMatrix build), which is why `--worker-cpu 3` and one worker. Bigger data per fit wants `NC8as_T4_v3` (8 vCPUs, 56 GB, same T4).

**Post a job.** The scheduler stands; a job is a client that connects to `tcp://gpu-scheduler.dask:8786` and submits tasks, like `gpu_stress.py` with `SCHEDULER_ADDRESS` set. Run it as a Job on the general pool (the ConfigMap holds the script; `kubectl apply -k config/dask/sample` would also apply the lab's `job.yaml`, which cannot schedule here):

```bash
kubectl -n dask create configmap gpu-concurrency-script --from-file=config/dask/sample/gpu_stress.py \
  --dry-run=client -o yaml | kubectl apply -f -
```

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: gpu-stress
  namespace: dask
spec:
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: dask-client
      restartPolicy: Never
      nodeSelector:
        agentpool: <general>              # the CPU pool
      tolerations:
        - operator: Exists
      containers:
        - name: client
          image: myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1
          command: ["python", "/scripts/gpu_stress.py"]
          env:
            - name: PYTHONPATH
              value: /devlab
            - name: SCHEDULER_ADDRESS
              value: tcp://gpu-scheduler.dask:8786
            - name: N_WORKERS
              value: "8"                  # at most the cluster's --workers
            - name: FITS
              value: "16"
          volumeMounts:
            - name: script
              mountPath: /scripts
            - name: devlab-dask
              mountPath: /devlab
      volumes:
        - name: script
          configMap:
            name: gpu-concurrency-script
        - name: devlab-dask
          configMap:
            name: devlab-dask
```

```bash
kubectl apply -f stress-job.yaml && kubectl -n dask logs -f job/gpu-stress
kubectl -n dask get pods -w             # workers as the DaskAutoscaler asks, nodes as the pool scales from 0
kubectl -n dask delete job gpu-stress   # before a re-run
```

Your own job is the same manifest with your script and image, and in the script `Client("tcp://gpu-scheduler.dask:8786")` then `client.submit`/`client.gather` ("Use It From Your Own Code" above). From your machine instead: `kubectl -n dask port-forward svc/gpu-scheduler 8786:8786 8787:8787`, then `SCHEDULER_ADDRESS=tcp://localhost:8786` with the cluster's dask/distributed versions, dashboard at http://localhost:8787/status. The first fit waits for a node to boot and pull the image (minutes); a worker Pending longer than that with `Insufficient nvidia.com/gpu` means the device plugin is not running on the GPU pool.

**Faster node scaling (AKS).** The cluster autoscaler decides within seconds: it scans every 10s and asks for all the nodes the Pending pods need at once, up to the pool's max. The minutes are Azure's: creating the VM, installing the GPU driver, starting the device plugin, then pulling the image. Scale-down is slow on purpose, 10 minutes idle by default. A profile that shortens the waits it controls (cluster-wide, so the CPU pools scale down sooner too):

```bash
az aks update -g <rg> -n <aks> --cluster-autoscaler-profile \
  scan-interval=10s new-pod-scale-up-delay=0s \
  max-node-provision-time=10m scale-down-delay-after-failure=1m \
  scale-down-delay-after-add=3m scale-down-unneeded-time=3m \
  skip-nodes-with-local-storage=false expander=least-waste
```

| Setting | Effect |
|---|---|
| `max-node-provision-time=10m` | A node that is not Ready in 10 minutes counts as failed (default 15m), so the autoscaler tries again or another pool sooner |
| `scale-down-delay-after-add=3m`, `scale-down-unneeded-time=3m` | Idle nodes go after 3 minutes instead of 10 to 20. Use the warm pool below to keep them through a session |
| `skip-nodes-with-local-storage=false` | Nodes whose pods use emptyDir (Dask workers spill there) can still be removed |
| `expander=least-waste` | With several GPU pools (zones, sizes), grows the one that fits best; a pool in backoff is skipped |

The bigger gains are outside the profile:

- **Deallocate instead of delete.** `--scale-down-mode Deallocate` stops idle VMs instead of deleting them. Scale-up then starts a stopped VM, with the driver installed and the image still in its cache: about a minute instead of 5 to 10. You pay for the stopped VMs' disks. It needs a managed OS disk (`--node-osdisk-type Managed`, fixed when the pool is created) and does not work with Spot. Check with `az aks nodepool show ... --query "{os:osDiskType, mode:scaleDownMode}"`; on an ephemeral pool, create a new one with both flags.
- **A floor during working hours.** `az aks nodepool update ... --update-cluster-autoscaler --min-count 2 --max-count 4` in the morning and `--min-count 0` at night, from a scheduled pipeline.
- **Artifact streaming** (ACR Premium): nodes start containers before the whole image has arrived. `az aks nodepool update ... --enable-artifact-streaming` plus `az acr artifact-streaming update -n <acr> --repository team/devlab-dask-gpu --enable-streaming true`; check its availability in your region first.
- **Regular priority, several zones.** Spot and single-zone pools fail to provision more often, and each failure costs a backoff.

**Warm the pool before a run.** A cold node costs a job minutes, and a job measured on a cold pool times all of that. `gpu_warm.py` scales the pool to N nodes, pulls the image on each, and keeps them there until you are done:

```bash
python3 config/dask/gpu_warm.py up --nodes 4 \
  --node-selector agentpool=t4 --toleration sku=gpu:NoSchedule \
  --image myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1 \
  --dask-autoscaler gpu
# Warming 4 nodes (agentpool=t4) with myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1
# DaskAutoscaler gpu: minimum 4 (was 0; `down` restores it)
#     0:00  nodes 1/4, images 1/4, GPUs 1/4, Dask workers 1/4
#     4:12  aks-t4-12345678-vmss000002 (westeurope-2): image pulled in 1m38s, nvidia.com/gpu 1
#     ...
# Warm after 6:05: 4 nodes with the image and nvidia.com/gpu, 4 Dask workers ready.
#   ... run the jobs ...
python3 config/dask/gpu_warm.py status
python3 config/dask/gpu_warm.py down    # restores the minimum; nodes go after scale-down-unneeded-time
```

It applies a Deployment `gpu-warm` of N tiny pods, one per node (required anti-affinity), each running the image, so the autoscaler adds nodes until there are N and each pulls the image. A node counts as warm when the image is pulled and the node advertises `nvidia.com/gpu`. The pods request 1m CPU and no GPU, so workers fit beside them, and the autoscaler cannot remove their nodes. `--dask-autoscaler gpu` also raises that DaskAutoscaler's minimum to N, so N workers start and connect before the job, and `up` waits for them too. Without it, workers start when a job arrives, from the cached image, in seconds. `--nodes` is the pool's max count (`az aks nodepool show ... --query maxCount`). On a timeout it prints why pods are Pending (`NotTriggerScaleUp`, quota, taints) and leaves the pods to keep trying. `--context` targets another cluster; `--image` repeats for several images.

**Measure the workers.** `gpu_metrics.py` samples every worker pod every 5 seconds and writes a CSV, then compares runs. Run the same job at each worker count, each with its own label:

```bash
python3 config/dask/gpu_metrics.py collect --label workers=4 --out w4.csv --job gpu-stress
#   0s  + gpu-default-worker-6f1c... on aks-t4-...-vmss000002
#   5s  workers 4  GPU util  97% (min 93)  GPU mem  21% (max 22)  CPU 1.04 cores/worker
#   ...
# Stopped: job gpu-stress finished
python3 config/dask/gpu_metrics.py summary w1.csv w2.csv w4.csv
# run                    time  workers GPUs  util  busy  p95 busy% GPUmem  max  maxMiB   CPU  %req  RAM%  err
# workers=1             ...
```

Each sample runs a small shell probe in the pod: CPU and memory from the container's cgroup (exact per interval, not the metrics-server's minute averages), GPU utilization and memory from `nvidia-smi`. The probe needs only `sh` in the container, and `nvidia-smi` for the GPU columns. It stops when `--job` has finished, when no worker has run for `--stop-after-idle` (60s), after `--duration`, or on Ctrl-C. `--selector` and `--container` point it at any pods, so the real workload is measured the same way. GPU numbers are per GPU: pods sharing a GPU report the same one, and the summary counts it once.

It runs from your machine through `kubectl` (`--context` for another cluster). To run it in the cluster on the CPU pool instead, `job` prints a Job with its own ServiceAccount and Role (pods list, `pods/exec`). It runs the script from the `devlab-dask` ConfigMap, so re-apply `kubectl apply -k config/dask` first. The Job's log is the CSV:

```bash
python3 config/dask/gpu_metrics.py job --label workers=4 --job gpu-stress \
  --node-selector agentpool=<general> --toleration all \
  --image myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1 | kubectl apply -f -
kubectl -n dask wait --for=condition=complete job/gpu-metrics --timeout=2h
kubectl -n dask logs job/gpu-metrics > w4.csv && kubectl -n dask delete job gpu-metrics
```

The Dask dashboard shows the same GPU figures live (http://localhost:8787/individual-gpu-utilization and `/individual-gpu-memory` through the port-forward); the worker's Prometheus endpoint has no GPU metrics. With `--rmm-pool` the GPU memory column shows the whole pool from the start, used or not.

**Compare worker counts.** To see how a job scales, keep the fit size fixed (`ROWS`, `COLUMNS`, `MAX_DEPTH`, `ROUNDS`) and the total work fixed (`FITS`, divisible by every worker count, e.g. 8 for 1, 2, 4 and 8 workers), and change only the number of workers. No new cluster is needed: the fit code travels from the client with each task, and each run's data cache is its own (`CACHE=run`). Refresh the script the Job mounts after pulling changes:

```bash
kubectl -n dask create configmap gpu-concurrency-script --from-file=config/dask/sample/gpu_stress.py \
  --dry-run=client -o yaml | kubectl apply -f -
```

`stress-sweep.yaml` is the Job from "Post a job" with `__N__` as the worker count:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: gpu-stress
  namespace: dask
spec:
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: dask-client
      restartPolicy: Never
      nodeSelector:
        agentpool: <general>
      tolerations:
        - operator: Exists
      containers:
        - name: client
          image: myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1
          command: ["python", "/scripts/gpu_stress.py"]
          env:
            - name: PYTHONPATH
              value: /devlab
            - name: SCHEDULER_ADDRESS
              value: tcp://gpu-scheduler.dask:8786
            - name: N_WORKERS
              value: "__N__"
            - name: FITS
              value: "8"
          volumeMounts:
            - name: script
              mountPath: /scripts
            - name: devlab-dask
              mountPath: /devlab
      volumes:
        - name: script
          configMap:
            name: gpu-concurrency-script
        - name: devlab-dask
          configMap:
            name: devlab-dask
```

The sweep holds the nodes warm (without `--dask-autoscaler`, so no extra workers), then for each count pins the DaskAutoscaler to exactly N workers, waits until N are ready, and runs the job with the collector:

```bash
python3 config/dask/gpu_warm.py up --nodes 8 --node-selector agentpool=t4 \
  --toleration sku=gpu:NoSchedule --image myacr.azurecr.io/team/devlab-dask-gpu:2026.1.1

for n in 1 2 4 8; do
  kubectl -n dask patch daskautoscaler gpu --type merge -p "{\"spec\":{\"minimum\":$n,\"maximum\":$n}}"
  # Ready and not Terminating (kubectl prints Terminating in the STATUS column)
  until [ "$(kubectl -n dask get pods -l dask.org/cluster-name=gpu,dask.org/component=worker --no-headers \
      | awk '$2 == "1/1" && $3 == "Running"' | wc -l)" -eq "$n" ]; do sleep 5; done
  kubectl -n dask delete job gpu-stress --ignore-not-found --wait
  sed "s/__N__/$n/" stress-sweep.yaml | kubectl apply -f -
  python3 config/dask/gpu_metrics.py collect --label "workers=$n" --out "w$n.csv" --job gpu-stress
  kubectl -n dask logs job/gpu-stress | tail -4 > "w$n.txt"
done

python3 config/dask/gpu_metrics.py summary w1.csv w2.csv w4.csv w8.csv
tail -n +1 w*.txt     # Data / Workers / Throughput / PASS lines of each run
kubectl -n dask patch daskautoscaler gpu --type merge -p '{"spec":{"minimum":0,"maximum":8}}'   # back to --workers
python3 config/dask/gpu_warm.py down
```

Ascending order means each step only adds workers on warm nodes. Compare:

- **Wall time and rounds/s** from each run's `Throughput` line; **speedup** is the 1-worker wall time over the N-worker one, **efficiency** the speedup over N. With one T4 per node, expect close to linear; the gap is data builds (`Data: built N times`), scheduling, and the last fit of the slowest worker.
- **Workers: X, at most Y fits at once** must show Y = N; a higher Y means the run did not use the script you meant.
- **GPU util** in the summary: near 100% busy per GPU means the GPUs were the limit; lower means the workers waited on data, CPU (`CPU`, `%req`) or the client.

`CACHE=off` makes every fit pay the data build, if the real workload has no data to reuse between fits.

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
