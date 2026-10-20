# GPU-Enabled Cluster

`devlab bootstrap --gpu` creates the dev-lab cluster with NVIDIA GPUs in its worker nodes and installs the [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html), so pods can request `nvidia.com/gpu`. Each physical GPU is [time-sliced](#time-slicing) into 4 shares by default. Everything else (registry, ingress, monitoring, addons, `deploy-gitops`) works as without `--gpu`.

GPUs are injected into the kind nodes the way [nvkind](https://github.com/NVIDIA/nvkind) does it, but devlab does it itself: the host needs only the NVIDIA driver, Docker and the NVIDIA Container Toolkit.

This page is the whole process, from a fresh machine to 4 GPU workloads sharing one GPU. Follow the steps in order; the sections after them are reference.

## Setup From Scratch

Written for Ubuntu (22.04 or newer) on a machine or VM with an NVIDIA GPU, with `sudo` and internet access. Allow about 40 GB of free disk for the node images, the GPU Operator and the Dask example image.

### 1. NVIDIA Driver

Skip this step if `nvidia-smi` already lists your GPU with a new enough driver.

**Driver version**: any driver whose `nvidia-smi` header shows CUDA Version 12.x (R525 or newer) runs CUDA 12 images, such as the RAPIDS image in the Dask runbook, through CUDA minor-version compatibility. CUDA 13 images need R580 or newer (CUDA Version 13.0). devlab turns off CUDA forward compatibility in the kind nodes, which would otherwise let some images try to run on an older driver, because it works only on datacenter GPUs and breaks images on GeForce cards and possibly vGPUs.

**Bare-metal GPU** (or a GPU passed through to a VM):

```bash
sudo apt update
sudo ubuntu-drivers install --gpgpu   # the recommended server driver
sudo reboot
```

**NVIDIA vGPU VM** (e.g. an A10-24Q profile): install the vGPU guest driver that matches your hypervisor's vGPU software release, from the NVIDIA Licensing Portal; the public driver does not work in a vGPU guest. A vGPU 18 (R570, CUDA 12.8) guest driver runs CUDA 12 images; CUDA 13 images need vGPU 19 (R580) or newer. Then license the VM with the client configuration token from the portal (or your DLS) ([NVIDIA docs](https://docs.nvidia.com/vgpu/latest/grid-licensing-user-guide/configuring-nls-licensed-client.html)):

```bash
sudo cp client_configuration_token_*.tok /etc/nvidia/ClientConfigToken/
sudo chmod 744 /etc/nvidia/ClientConfigToken/client_configuration_token_*.tok
# FeatureType=1 for a vGPU (the license type follows the vGPU profile)
sudo cp -n /etc/nvidia/gridd.conf.template /etc/nvidia/gridd.conf
echo 'FeatureType=1' | sudo tee -a /etc/nvidia/gridd.conf
sudo systemctl restart nvidia-gridd
```

Check:

```bash
nvidia-smi                                   # GPU listed, driver and CUDA version in the header
nvidia-smi -q | grep -i 'license status'     # vGPU only: Licensed (Expiry: ...)
```

### 2. Docker

Skip this step if `docker run --rm hello-world` works without `sudo`.

```bash
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in
docker run --rm hello-world
```

### 3. NVIDIA Container Toolkit

Lets Docker give containers, and so the kind nodes, access to the GPU.

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install -y nvidia-container-toolkit

# Make nvidia Docker's default runtime, and let a /dev/null mount at
# /var/run/nvidia-container-devices/<gpu> request a GPU (how kind nodes get theirs)
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default --cdi.enabled
sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place
sudo systemctl restart docker    # restarts every container on this host

# kind nodes share the host's inotify limits; the GPU Operator's device plugin
# fails with "too many open files" at the default 128 instances
printf 'fs.inotify.max_user_instances = 8192\nfs.inotify.max_user_watches = 524288\n' | \
  sudo tee /etc/sysctl.d/99-devlab-kind.conf
sudo sysctl --system
```

Check (must list your GPU):

```bash
docker run --rm -v /dev/null:/var/run/nvidia-container-devices/all ubuntu:22.04 nvidia-smi -L
```

Time slicing needs the GPU in the `Default` compute mode, with no MPS server on the host. Some VMs and GPU servers are set up with `Exclusive_Process` and an MPS daemon; then pods fail with `CUDA-capable device(s) is/are busy or unavailable`. If nothing else on the host uses MPS:

```bash
nvidia-smi -q | grep -i "compute mode"                     # must be Default
nvidia-smi --query-compute-apps=pid,name --format=csv      # nvidia-cuda-mps-server listed? then:
systemctl list-units --all | grep -i mps                   # started by a service? stop and disable it
echo quit | sudo nvidia-cuda-mps-control                   # stop the MPS daemon and its server
sudo nvidia-smi -c DEFAULT
```

The compute mode resets to Default at reboot unless a service sets it; disable that service too.

`devlab bootstrap --gpu` runs the GPU check, the compute mode check and the inotify check first.

### 4. devlab

```bash
sudo apt install -y python3 python3-venv python3-pip git fzf   # fzf: optional, for the Kubernetes version picker
git clone https://github.com/JB0t/dev-lab.git
cd dev-lab
python3 python/setup.py

# devlab on PATH, with tab completion
printf '\nexport PATH="$PATH:%s"\n' "$(pwd)/python" >> ~/.bashrc
printf 'source <(devlab completion bash)\n' >> ~/.bashrc
source ~/.bashrc
```

**Behind TLS inspection** (a corporate proxy that re-signs HTTPS): copy its CA certificate(s) into `python/certs/` as `.crt` files now. devlab builds them into its tool images and installs them into the kind nodes, before the GPU setup downloads packages there.

### 5. Bootstrap the GPU Cluster

```bash
devlab bootstrap --gpu
```

It asks which Kubernetes version to use (Enter keeps the default), then runs for 10 to 20 minutes: cluster, GPU node setup, registry, Traefik, monitoring, then the GPU Operator. If an optional component such as the monitoring stack fails, bootstrap still installs everything else, including the GPU Operator, lists the failed components at the end and exits with an error; re-run `devlab bootstrap --gpu` and keep the existing cluster to retry them. It ends with `NVIDIA GPU Operator ready` and the access points (Grafana at <http://grafana.localhost>, admin / admin123).

By default the first worker gets every GPU and the second worker is CPU-only; see [GPU Placement](#gpu-placement) to change this before bootstrapping.

### 6. Verify

```bash
devlab status                                            # GPUs column: GiB of GPU memory on dev-lab-worker
devlab kubectl get pods -n gpu-operator                  # all Running or Completed
devlab kubectl apply -f config/gpu/gpu-test-pod.yaml
devlab kubectl logs gpu-test                             # ... Test PASSED (a CUDA vector addition on the GPU)
devlab kubectl delete pod gpu-test
```

GPU metrics are in Prometheus and Grafana: query `DCGM_FI_DEV_GPU_UTIL` in Grafana's Explore view.

### 7. Dask GPU Workers That Scale From 0

[DASK-GPU-RUNBOOK.md](./DASK-GPU-RUNBOOK.md) builds the Dask image from the pinned versions, installs the Dask Kubernetes Operator, and runs a sample client that creates a Dask cluster with 0 GPU workers, submits 4 GPU tasks, and shows the scheduler scaling to 4 workers that use the GPU at the same time. In short:

```bash
devlab build -t devlab-dask-gpu:2026.1.1 --push config/dask/image   # ~10 minutes
devlab addon enable dask-operator
devlab kubectl apply -k config/dask
devlab kubectl apply -k config/dask/sample
devlab kubectl -n dask logs -f job/gpu-concurrency                    # expect: PASS
```

For existing code that connects with `Client("tcp://<address>:8786")`, run a standing cluster instead and point the client at `tcp://<server IP>:8786`. Anyone who can reach that port can run code on the GPU workers, so firewall it as the runbook describes. See "Connect Existing Clients By Address" in the runbook:

```bash
python3 config/dask/devlab_dask.py gpu --workers 4 --gpu-memory-gib 5 | devlab kubectl apply -n dask -f -
```

To launch the same kind of work from a UI, enable Dagster. Then open **http://dagster.localhost**, go to Jobs, then `gpu_concurrency_job`, then Launchpad, and Launch Run. Each run creates its own time-sliced GPU Dask cluster and runs every op on its workers (see "Run From Dagster" in the runbook):

```bash
devlab addon enable dagster
```

**Headless server**: open the dashboards from your own machine through an SSH tunnel to the server's port 80, where Traefik serves every `*.localhost` site. Browsers send `*.localhost` to your own machine, so the tunnel carries the requests to the server and Traefik picks the site by its name:

```bash
# On your machine; leave it running. 8080 because ports below 1024 need root
ssh -N -L 8080:localhost:80 user@gpu-server
```

Then browse to http://dagster.localhost:8080, and likewise http://grafana.localhost:8080 or http://prometheus.localhost:8080. To keep the tunnel in your SSH config, so a plain `ssh gpu-server` opens it:

```text
# ~/.ssh/config on your machine
Host gpu-server
    HostName <server address>
    User <user>
    LocalForward 8080 localhost:80
```

With `LocalForward 80 localhost:80` (and `sudo ssh ...`, since port 80 needs root on your machine) the URLs work without `:8080`. VS Code Remote-SSH can forward the port too: Ports panel > Forward a Port > `80`.

kind publishes port 80 on every interface of the server, so anyone who can reach the server can open these dashboards. The Dagster UI has no login and can launch runs. A `ufw` rule does not stop this, because Docker's published ports bypass `ufw`. To allow access only through SSH:
1. Add `listenAddress: 127.0.0.1` to the port 80 and 443 entries under `extraPortMappings` in `cluster/kind-config.yaml`. Bootstrap `--gpu` builds its config from this file.
2. Recreate the cluster: `devlab cleanup && devlab bootstrap --gpu`.
3. From another machine, check that `curl -H 'Host: dagster.localhost' http://<server address>/` no longer connects.

### 8. Clean Up

```bash
devlab cleanup
```

To undo the host setup, revert step 3 with `sudo nvidia-ctk runtime configure --runtime=docker --set-as-default=false`, `sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=false --in-place` and `sudo systemctl restart docker`.

## What Bootstrap Does

1. Builds the kind config from the profile's config (`cluster/kind-config.yaml`, or `kind-config.ci.yaml`) with its workers replaced by the ones in `cluster/gpu-workers.yaml`, and writes it to `.kube/kind-config.gpu.yaml`. Each GPU worker gets a `/dev/null` mount at `/var/run/nvidia-container-devices/<device>` (the host's nvidia-container-runtime turns it into that GPU) the labels `nvidia.com/gpu.present=true` and `devlab.io/gpu=true`, and the taint `nvidia.com/gpu=present:NoSchedule`. The control plane and CPU-only workers get `nvidia.com/gpu.deploy.operands=false` and `devlab.io/gpu=false`.
2. Creates the cluster and installs the custom CA certificates, as without `--gpu`.
3. In each GPU worker, installs the NVIDIA Container Toolkit and adds an `nvidia` containerd runtime (nvkind's node setup), with CUDA forward compatibility turned off (see [step 1](#1-nvidia-driver)). This runs after the CA certificates so `apt` works behind TLS inspection.
4. Installs the registry, metrics-server, Traefik and the monitoring stack.
5. Applies the `nvidia` RuntimeClass and installs the GPU Operator (`config/gpu/gpu-operator-values.yaml`) in the `gpu-operator` namespace, with one time-slicing share per GiB of GPU memory. It runs the device plugin (with the time-slicing config), GPU feature discovery, node feature discovery, the DCGM exporter and the operator validator. The driver and toolkit operands are off: the nodes already have both. The validator skips its CUDA sample workloads, which need CUDA forward compatibility on drivers older than CUDA 12.9; the smoke test in step 6 runs a CUDA workload instead.
6. Waits until a node advertises allocatable `nvidia.com/gpu` (the GPU memory in GiB).

Masking `/proc/driver/nvidia/params` and removing unassigned `/dev/nvidia*` nodes can fail harmlessly on some toolkit versions. Bootstrap logs these as warnings and continues; the GPU capacity check catches a real failure.

## GPU Placement

By default the first worker gets every host GPU and the second worker is CPU-only. Edit `cluster/gpu-workers.yaml` to change this. Each `workers` entry is one worker node, and `devices` takes a GPU index, a list of indexes, or `all`. GPU workers are tainted for GPU workloads only; add `taint: false` to a worker to allow any pod there. Keep at least one CPU-only worker for CPU pods such as the Dask scheduler:

```yaml
# One GPU per worker on a 2-GPU host
workers:
- devices: 0
- devices: 1
```

Recreate the cluster (`devlab bootstrap --gpu`, answer yes to recreate) to apply changes.

## Time Slicing

The device plugin [time-slices](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-sharing.html) each physical GPU into **one `nvidia.com/gpu` share per GiB of GPU memory**: bootstrap reads the GPU's memory and sets the share count (an A10-24Q advertises 22, an 11 GB card 10). A pod requests as many shares as the GiB of GPU memory it may use, so Kubernetes only places it on a node with that much GPU memory still free, and pods of different sizes pack onto the same GPU. The GPU switches between their CUDA contexts.

**Time slicing gives no memory or fault isolation.** Every pod sees the whole GPU and its full memory. Shares only make Kubernetes count GPU memory; each workload must still keep to the memory it requested, or it can make the others fail with out-of-memory errors. The Dask helper can do this for code that allocates through RMM: each worker gets a fixed RMM pool the size of its shares. XGBoost allocates its own memory, so size its workers for their peak use. A crash or GPU fault in one pod can also affect the others.

Other effects:

- A share is not a fixed fraction of compute. A pod alone on the GPU gets all of it, and busy pods take turns.
- The resource name stays `nvidia.com/gpu`; `nvidia.com/gpu: 1` now means 1 GiB.
- With several GPUs in one node, a pod's shares can come from different GPUs. Give each GPU its own kind worker node in `cluster/gpu-workers.yaml` (`devices: 0`, `devices: 1`, ...).

The config is `devicePlugin.config` in `config/gpu/gpu-operator-values.yaml`:

```bash
# Fixed share count instead of 1 per GiB: replace ${GPU_MEMORY_GIB} with a number (>= 2), then
devlab gpu-operator

# Turn time slicing off for the whole cluster: set `default: exclusive`, then
devlab gpu-operator

# Turn it off on one node only (no reinstall; the plugin picks up the label change itself)
devlab kubectl label node dev-lab-worker nvidia.com/device-plugin.config=exclusive --overwrite
# ...and back on
devlab kubectl label node dev-lab-worker nvidia.com/device-plugin.config-
```

`devlab gpu-operator` re-runs the GPU Operator Helm install and waits for the new capacity. Pods already running on shares keep running, so delete them first if you reduce the share count.

For Dask clusters whose GPU workers scale from 0, with a GPU memory size chosen by the client, see [DASK-GPU-RUNBOOK.md](./DASK-GPU-RUNBOOK.md).

## MPS Instead of Time Slicing (Experimental)

Time slicing runs one pod's CUDA context at a time and switches between them, so the GPU's total utilisation cannot exceed what one pod reaches alone. Workloads that launch many short kernels with CPU work in between (XGBoost `hist`, for one) leave it mostly idle, and four time-sliced pods still do. [CUDA MPS](https://docs.nvidia.com/deploy/mps/latest/index.html) runs kernels of several processes on the GPU at the same time. The device plugin supports it as another sharing config (`mps` in `config/gpu/gpu-operator-values.yaml`): it runs an MPS control daemon on the node, and every pod on a share goes through it.

What changes with MPS:

- **Equal slices, not GiB shares.** The daemon limits each client to `1/replicas` of the GPU memory and of its SMs (`replicas: 4` on an A10-24Q: 5.5 GiB and 25% each). A pod takes exactly one share (`nvidia.com/gpu: 1`; more is refused), so with 4 replicas 4 pods run at once, whatever their memory needs. Pods of different sizes cannot pack as with GiB shares.
- **Less isolation.** The memory limit is enforced in software, and a fatal GPU error in one client can stop the others.
- **Compute mode.** The daemon sets the GPU to `Exclusive_Process` while it runs (on the host too: the kind node shares the host driver) and back to `Default` when it stops. `devlab bootstrap --gpu` refuses a GPU that is not in `Default` mode, so switch back before recreating the cluster, or set the mode by hand (step 3 of Setup).
- **vGPU guests.** NVIDIA documents MPS for bare-metal GPUs, but it works inside a Q-series vGPU: measured on an A10-24Q with the GPU sample (XGBoost, 30 s tasks), one worker alone trained 2510 rounds and four at once 2330, 2350, 2330 and 2320, i.e. 3.7x the throughput, each at 93% of its solo speed. Under time slicing the four share one worker's rounds. The stress test (`gpu_stress.py`, fits of 2 M x 64 rows, depth 10, 200 rounds) scaled 2.0x: 11.3 rounds/s with one worker (2 fits, 35.3 s), 21.7 rounds/s with two (4 fits, 37.9 s) and 22.7 rounds/s with four (8 fits, 70.5 s), each fit then at about half its solo speed. GPU memory in use stayed near 25% of the card (about 1.5 GiB per fit: the QuantileDMatrix holds 8-bit bins, not the float32 data), so memory is not what limits it. Using that memory to keep the dataset on the worker between fits (`DATASETS=1`) took two workers from 22.5 to 29 rounds/s over eight fits. A fit this big alone already uses about half the GPU, so there is less idle time for MPS to fill than with the small sample; scaling past 2x needs lighter fits or a bigger GPU, not more workers.

**Switch to MPS** for every GPU node. This re-runs the operator install with `mps` as the device plugin's default config, so the plugin, GPU feature discovery and the MPS control daemon all use it (the daemon runs where the node is labelled `nvidia.com/mps.capable=true`):

```bash
devlab gpu-operator --sharing mps
devlab kubectl get node dev-lab-worker -o jsonpath='{.status.allocatable.nvidia\.com/gpu}{"\n"}'   # 4
devlab kubectl -n gpu-operator get pods -o wide | grep -E 'device-plugin|mps'                       # plugin + mps-control-daemon Running on dev-lab-worker
devlab kubectl -n gpu-operator logs ds/nvidia-device-plugin-mps-control-daemon --all-containers | grep -i -E 'limit|percentage|strategy'
```

The per-node label (`nvidia.com/device-plugin.config=mps`, as for `exclusive`) switches the plugin and feature discovery but not reliably the daemon, which then logs `Sharing strategy is not MPS` and the node advertises no shares; remove the label (`nvidia.com/device-plugin.config-`) when using `--sharing`.

Pods on time-sliced shares keep running until deleted; a Dask cluster made for GiB shares asks for 5 shares per worker, which MPS refuses, so recreate it with **1 share per worker** and the slice's memory as its limit:

```bash
devlab kubectl -n dask delete daskcluster gpu
devlab kubectl -n dask delete ingress gpu-dashboard
python3 config/dask/devlab_dask.py gpu --workers 4 --gpu-shares 1 --gpu-memory-gib 5 | devlab kubectl apply -n dask -f -
```

`gpu_cluster(...)` takes the same `gpu_shares=1`; the sample job reads it from `GPU_SHARES` (`config/dask/sample/job.yaml`), Dagster from `gpu_shares` in the Launchpad config.

**Compare** with the GPU sample in address mode (see DASK-GPU-RUNBOOK.md): run it with `N_WORKERS=1` and `N_WORKERS=4` under time slicing, then under MPS, and compare the `rounds` column. For a load like a real model-fitting job, the stress test in the same place (`gpu_stress.py`, "Stress Test: A Grid Of Fits") reports the total rounds/s of a grid of big fits. Time slicing: four workers together get about one worker's rounds. MPS working: each of the four gets a good part of what one gets alone, and `nvidia-smi` on the host shows one `nvidia-cuda-mps-server` process instead of four workers. MPS not helping: the same numbers as time slicing, or workers failing to start (see Troubleshooting).

**Back to time slicing:**

```bash
devlab gpu-operator --sharing time-sliced
# The node advertises its GiB shares again (22 on an A10-24Q); then recreate the Dask cluster without --gpu-shares
nvidia-smi -q | grep -i "compute mode"     # on the host: Default again; else sudo nvidia-smi -c DEFAULT
```

## Running GPU Workloads

GPU nodes are tainted `nvidia.com/gpu=present:NoSchedule`, so only GPU workloads run there and everything else, such as the Dask scheduler, stays on the CPU worker. GPU pods must:

- request `nvidia.com/gpu`: the GiB of GPU memory they may use,
- set `runtimeClassName: nvidia` (the nvidia runtime is not the containerd default on the nodes),
- tolerate the GPU taint:

```yaml
spec:
  runtimeClassName: nvidia
  tolerations:
    - key: nvidia.com/gpu
      operator: Exists
      effect: NoSchedule
  containers:
    - name: app
      image: my-gpu-app:latest
      resources:
        limits:
          nvidia.com/gpu: 4   # 4 GiB of GPU memory; keep the app to that
```

Nodes are labelled `devlab.io/gpu=true` (GPU workers) or `devlab.io/gpu=false` (all others), for `nodeSelector`s.

Smoke test:

```bash
devlab kubectl apply -f config/gpu/gpu-test-pod.yaml
devlab kubectl logs gpu-test     # ... Test PASSED
devlab kubectl delete pod gpu-test

# Allocatable GPU shares per node (GPUs column: GiB of GPU memory)
devlab status
```

## GPU Metrics

With the monitoring stack installed, the DCGM exporter's ServiceMonitor is scraped by Prometheus: GPU utilization, memory, temperature and power per GPU, e.g. `DCGM_FI_DEV_GPU_UTIL` and `DCGM_FI_DEV_FB_USED` in Grafana's Explore view (`http://grafana.localhost`). With `--no-monitoring` the ServiceMonitor is left out.

GPU feature discovery adds labels such as `nvidia.com/gpu.product` and `nvidia.com/gpu.memory` to GPU nodes: `devlab kubectl get node dev-lab-worker --show-labels`.

## vGPU Guests (e.g. A10-24Q)

The setup is the same inside a VM with an NVIDIA vGPU. `nvidia-smi -L` shows the vGPU profile, e.g. `GPU 0: NVIDIA A10-24Q (UUID: GPU-...)`. Differences from a bare-metal GPU:

- **Guest driver**: install the NVIDIA vGPU guest driver from the NVIDIA Licensing Portal. It must match the vGPU software release of the hypervisor's vGPU manager. The public data center driver does not work in a vGPU guest. The NVIDIA Container Toolkit and devlab work the same on top of it.
- **Licensing**: see [step 1](#1-nvidia-driver). An unlicensed vGPU runs at full capability for 20 minutes; after that NVIDIA degrades its performance, and degrades it further after 24 hours. The exact effect on CUDA depends on the vGPU release; see the [licensing guide](https://docs.nvidia.com/vgpu/latest/grid-licensing-user-guide/intro-to-grid-licensing.html). `devlab bootstrap --gpu` warns, but continues, when the vGPU is unlicensed.
- **CUDA version**: CUDA 12 images run on any vGPU 16 (R535) or newer guest driver through minor-version compatibility, e.g. CUDA 12.9 images on a CUDA 12.8 (R570) guest. CUDA 13 images need an R580+ driver. Check the driver's CUDA version in the `nvidia-smi` header.
- **No MIG on A10**: an A10 cannot be partitioned with MIG, so time slicing is the only way to share it between pods.
- **Unified memory**: CUDA unified (managed) memory is off by default on vGPUs. Your hypervisor admin must turn it on per vGPU, and NVIDIA documents it only for some profiles. Don't rely on managed memory (e.g. RMM managed memory) unless you have checked it is enabled.
- **Full-GPU profile**: A10-24Q uses the whole 24 GB A10, so no other VM shares the physical GPU. `nvidia-smi` in the guest reports slightly less than 24 GB total because of vGPU-reserved memory.


## Troubleshooting

- **No node advertised nvidia.com/gpu capacity**: check the operator pods with `devlab kubectl get pods -n gpu-operator`; the validator and device plugin logs usually say why. Did you keep an existing cluster that was created without `--gpu`? Then delete it and re-bootstrap: `devlab cleanup && devlab bootstrap --gpu`.
- **`<node> has no GPUs: the existing cluster was not created with --gpu`**: same fix, recreate the cluster.
- **MPS: node still advertises the GiB share count, or no `mps-control-daemon` pod**: `devlab kubectl -n gpu-operator logs ds/nvidia-device-plugin-daemonset --all-containers | tail -30` (the config-manager sidecar says which config it applied); check the node has `nvidia.com/mps.capable=true` (`devlab kubectl get node dev-lab-worker --show-labels`).
- **MPS: node advertises 0 shares and the daemon logs `Sharing strategy is not MPS`**: the daemon runs with the time-sliced config; the plugin advertises nothing until the daemon is up. Switch with `devlab gpu-operator --sharing mps` rather than the node label, and remove the label.
- **MPS: workers stay `Pending` with `UnexpectedAdmissionError`**: they request more than one share; recreate the Dask cluster with `--gpu-shares 1`.
- **MPS: workers fail with `CUDA_ERROR_...` at start, or the daemon logs `failed to start MPS server`**: MPS did not come up on this GPU (a vGPU guest may not allow it); switch back to time slicing.
- **Failed installing the NVIDIA Container Toolkit**: the GPU node could not reach `nvidia.github.io` or the Ubuntu/Debian mirrors. Behind TLS inspection, put the CA certificate in `python/certs/` (see the README).
- **Pod stuck in Pending**: not enough free GPU shares (GiB) on any GPU node, or the pod does not tolerate the `nvidia.com/gpu` taint. Check with `devlab status` and `devlab kubectl describe pod <pod>`.
- **Pod fails with `UnexpectedAdmissionError`**: its shares could not be allocated on the node it was placed on; check the device plugin logs. With `default: exclusive`, pods get whole GPUs and requests above the GPU count fail.
- **`CUDA_ERROR_OUT_OF_MEMORY` with time slicing**: another pod on the same GPU used the memory. Limit each workload's GPU memory (see [Time Slicing](#time-slicing)).
- **`requirement error: unsatisfied condition: cuda>=...`**: the image needs a newer driver than the host or vGPU guest has. Use an image built for an older CUDA version.
- **GPU slows down after ~20 minutes in a VM**: the vGPU is not licensed (see [vGPU Guests](#vgpu-guests-eg-a10-24q)).
- **Device plugin in CrashLoopBackOff with `couldn't initialize inotify: too many open files`**: raise the host's inotify limits ([step 3](#3-nvidia-container-toolkit)), then `devlab kubectl -n gpu-operator delete pod -l app=nvidia-device-plugin-daemonset`.
- **`forward compatibility was attempted on non supported HW`**: CUDA forward-compatibility libraries from the image were loaded on a GPU that does not support them. devlab turns this off in the GPU nodes; if you see it, the node setup did not finish: re-run `devlab bootstrap --gpu`.
- **`CUDA driver version is insufficient for CUDA runtime version`**: the image is built for a newer CUDA major version than the driver (e.g. a CUDA 13 image on a 12.x driver). Use a CUDA 12 image, or upgrade the driver ([step 1](#1-nvidia-driver)).
- **`CUDA-capable device(s) is/are busy or unavailable`**: the GPU is in `Exclusive_Process` compute mode, or a host MPS server holds it. Set the Default mode and stop MPS ([step 3](#3-nvidia-container-toolkit)), then `devlab kubectl -n gpu-operator delete pod -l app=nvidia-device-plugin-daemonset` and re-run the workload.
- **`nvidia-smi: not found` in the pod**: the pod is missing `runtimeClassName: nvidia`.
- **GPUs a node sees**: `docker exec dev-lab-worker nvidia-smi -L`.
