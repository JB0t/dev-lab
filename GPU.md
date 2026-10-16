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

[DASK-GPU-RUNBOOK.md](./DASK-GPU-RUNBOOK.md) builds the Dask image from the pinned versions, installs the Dask Kubernetes Operator, and runs a sample client that creates a Dask cluster with 0 GPU workers, submits 4 GPU tasks, and shows the scheduler scaling to 4 workers that use the GPU at the same time.

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

**Time slicing gives no memory or fault isolation.** Every pod sees the whole GPU and its full memory. Shares only make Kubernetes count GPU memory; each workload must still keep to the memory it requested, or it can make the others fail with out-of-memory errors. The Dask helper does this for you: each worker gets a fixed RMM pool the size of its shares. A crash or GPU fault in one pod can also affect the others.

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
