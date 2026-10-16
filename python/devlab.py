"""
Dev Lab - Platform-Agnostic Kubernetes Development Environment

A complete Kubernetes development environment using Docker as a dependency.

Features:
- Platform-agnostic (Windows, macOS, Linux)
- Uses containers for all tools (kubectl, helm, linkerd, etc.)
- No local tool installation required except Docker
- Virtual environment for Python dependencies
- Clean, maintainable Python code instead of bash
"""

import os
import sys
import platform
import subprocess
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import time
import re
import shutil
import threading
import hashlib
import socket
import copy

# Third-party imports (will be in requirements.txt)
import click
from click.shell_completion import CompletionItem, get_completion_class
import docker
import yaml
import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import print as rprint

# Initialize console for rich output
console = Console()

# Constants
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
CLUSTER_NAME = "dev-lab"
REGISTRY_PORT = 5000
KEY_PATH = str(PROJECT_ROOT / "flux-deploy-key")
REPO_URL = "ssh://git@github.com/jbotstevens/notes.git"
KIND_NODE_REPOSITORY = "kindest/node"
KIND_NODE_TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
DEFAULT_KIND_NODE_IMAGE = "kindest/node:v1.35.8"

# Container tool versions
TOOL_VERSIONS = {
    "kubectl": "v1.28.3",
    "helm": "v3.13.1",
    "linkerd": "stable-2.14.5",
    "kind": "v0.33.0",
    "flux": "v2.1.2",
    "krew": "v0.4.5",
}

# Krew plugins installed into the containerized kubectl on first use
DEFAULT_KREW_PLUGINS = ["ctx", "gpugo", "neat", "ns", "tree", "who-can"]

REGISTRY_HOST = f"localhost:{REGISTRY_PORT}"

# Profiles select defaults for where devlab runs. "ci" is for pipelines,
# typically with a Docker-in-Docker daemon (see CI.md): no prompts, a smaller
# cluster, and no monitoring stack or krew plugins unless asked for.
PROFILES = {
    "local": {"kind_config": "kind-config.yaml", "monitoring": True, "krew": True},
    "ci": {"kind_config": "kind-config.ci.yaml", "monitoring": False, "krew": False},
}
ACTIVE_PROFILE = "local"


def profile_setting(key: str):
    return PROFILES[ACTIVE_PROFILE][key]


def interactive_session() -> bool:
    """Prompts are allowed only for local use from a terminal."""
    return ACTIVE_PROFILE == "local" and sys.stdin.isatty()
TRAEFIK_CHART_VERSION = "41.6.0"

# Addon versions (devlab addon enable ...)
KEDA_CHART_VERSION = "2.20.2"
KWOK_VERSION = "v0.8.0"
CLUSTER_AUTOSCALER_CHART_VERSION = "9.59.0"
# cluster-autoscaler must match the cluster's Kubernetes minor version
CLUSTER_AUTOSCALER_IMAGE_TAGS = {
    (1, 33): "v1.33.6",
    (1, 34): "v1.34.5",
    (1, 35): "v1.35.2",
    (1, 36): "v1.36.1",
}

# GPU-enabled clusters (bootstrap --gpu). GPUs are added to the kind workers
# the way nvkind does, and the NVIDIA GPU Operator runs on top.
GPU_OPERATOR_CHART_VERSION = "v26.7.1"
NVIDIA_DEVICES_DIR = "/var/run/nvidia-container-devices"
GPU_PROBE_IMAGE = "ubuntu:22.04"
GPU_NODE_LABEL = "nvidia.com/gpu.present"
# The GPU Operator runs no operands on nodes with this label set to "false"
GPU_OPERANDS_LABEL = "nvidia.com/gpu.deploy.operands"

# Services published through the Traefik ingress. *.localhost resolves to
# loopback in browsers and curl without any /etc/hosts entries.
# (service, URL, credentials, part of the monitoring stack)
ACCESS_POINTS = [
    ("Grafana", "http://grafana.localhost", "admin/admin123", True),
    ("Prometheus", "http://prometheus.localhost", "-", True),
    ("Alertmanager", "http://alertmanager.localhost", "-", True),
    ("Registry UI", "http://registry.localhost", "-", False),
    ("Traefik dashboard", "http://traefik.localhost/dashboard/", "-", False),
    ("Registry API", f"http://{REGISTRY_HOST}/v2/_catalog", "-", False),
]
DOCKER_ARCHITECTURES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
}


def docker_architecture() -> str:
    """Return the Docker daemon architecture using Go/Docker naming."""
    result = subprocess.run(
        ["docker", "info", "--format", "{{.Architecture}}"],
        capture_output=True,
        text=True,
    )
    architecture = DOCKER_ARCHITECTURES.get(result.stdout.strip())
    if result.returncode != 0 or not architecture:
        raise RuntimeError(f"Could not determine Docker architecture: {result.stderr.strip()}")
    return architecture


def interactive_terminal() -> bool:
    """True when both stdin and stdout are attached to a terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()

class DevLabError(Exception):
    """Custom exception for dev-lab operations"""
    pass


def worker_node_name(index: int) -> str:
    """KinD names workers dev-lab-worker, dev-lab-worker2, ... in config order."""
    return f"{CLUSTER_NAME}-worker" + ("" if index == 0 else str(index + 1))


def gpu_worker_devices(worker) -> List[str]:
    """Normalise a gpu-workers.yaml `devices` value to a list of strings."""
    devices = worker.get("devices") if isinstance(worker, dict) else None
    if devices is None:
        return []
    if not isinstance(devices, list):
        devices = [devices]
    result = []
    for device in devices:
        if device == "all" or (isinstance(device, int) and not isinstance(device, bool) and device >= 0):
            result.append(str(device))
        else:
            raise DevLabError(
                f"cluster/gpu-workers.yaml: invalid device {device!r} "
                "(use a GPU index, a list of indexes, or all)"
            )
    return result


def gpu_kind_config(config: dict, workers: list) -> Tuple[dict, Dict[str, List[str]]]:
    """Replace the workers of a kind config with the GPU workers of gpu-workers.yaml.

    Each GPU is injected the way nvkind does it: a /dev/null mount at
    /var/run/nvidia-container-devices/<device>, which the host
    nvidia-container-runtime turns into that GPU. Returns the new config and
    {node name: devices} for the workers that have GPUs.
    """
    if not workers:
        raise DevLabError("cluster/gpu-workers.yaml has no workers")
    config = copy.deepcopy(config)
    nodes = config.get("nodes") or [{"role": "control-plane"}]
    control_planes = [node for node in nodes if node.get("role") != "worker"]
    templates = [node for node in nodes if node.get("role") == "worker"] or [{"role": "worker"}]

    # NFD sees the host's GPUs from every kind node; keep GPU Operator
    # operands off the nodes that have none
    for node in control_planes:
        node["labels"] = {**(node.get("labels") or {}), GPU_OPERANDS_LABEL: "false"}

    gpu_nodes = {}
    new_workers = []
    for index, worker in enumerate(workers):
        node = copy.deepcopy(templates[min(index, len(templates) - 1)])
        node["role"] = "worker"
        devices = gpu_worker_devices(worker)
        labels = dict(node.get("labels") or {})
        if devices:
            labels[GPU_NODE_LABEL] = "true"
            node["extraMounts"] = list(node.get("extraMounts") or []) + [
                {"hostPath": "/dev/null", "containerPath": f"{NVIDIA_DEVICES_DIR}/{device}"}
                for device in devices
            ]
            gpu_nodes[worker_node_name(index)] = devices
        else:
            labels[GPU_OPERANDS_LABEL] = "false"
        node["labels"] = labels
        new_workers.append(node)

    if not gpu_nodes:
        raise DevLabError("cluster/gpu-workers.yaml gives no worker any GPU devices")
    config["nodes"] = control_planes + new_workers
    return config, gpu_nodes


def allocatable_gpus(nodes_json: str) -> Dict[str, str]:
    """Nodes with non-zero allocatable nvidia.com/gpu, from `kubectl get nodes -o json`."""
    result = {}
    for node in json.loads(nodes_json).get("items", []):
        count = node.get("status", {}).get("allocatable", {}).get("nvidia.com/gpu", "0")
        if count not in ("", "0"):
            result[node["metadata"]["name"]] = count
    return result


# Node setup scripts for GPU workers, adapted from nvkind's pkg/nvkind/node.go
# (https://github.com/NVIDIA/nvkind, Apache-2.0). They run in each GPU node
# after the custom CA certificates are installed, so apt works behind TLS
# inspection.
INSTALL_TOOLKIT_SCRIPT = """
set -e
apt-get update
apt-get install -y gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \\
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \\
  tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
apt-get install -y nvidia-container-toolkit
"""

CONFIGURE_RUNTIME_SCRIPT = """
set -e
nvidia-ctk runtime configure --runtime=containerd --config-source=file
systemctl restart containerd
"""

# Toolkits older than v1.19.0 bind-mount a tmpfs over /proc/driver/nvidia,
# hiding the real params file. Expose it, set ModifyDeviceFiles to 0 and
# bind-mount the copy back, so the driver does not recreate device nodes.
PATCH_PROC_DRIVER_SCRIPT = """
set -e
umount -R /proc/driver/nvidia
cp /proc/driver/nvidia/params root/gpu-params
sed -i 's/^ModifyDeviceFiles: 1$/ModifyDeviceFiles: 0/' root/gpu-params
mount --bind root/gpu-params /proc/driver/nvidia/params
"""

REMOVE_DEVICE_NODE_SCRIPT = """
while umount /dev/nvidia{index}; do :; done || true
rm -rf /dev/nvidia{index}
"""

class ContainerToolRunner:
    """Runs Kubernetes tools in containers for platform independence"""

    _filesystem_checked = False

    def _check_docker_filesystem(self):
        """Fail early when the Docker daemon cannot see this machine's files.

        The tool containers bind-mount the project and the current directory.
        With a remote daemon, such as a docker:dind service in CI, bind mount
        paths resolve on the daemon's filesystem, so they must be shared with
        it at the same path (see CI.md).
        """
        docker_host = os.environ.get("DOCKER_HOST", "")
        if ContainerToolRunner._filesystem_checked or not docker_host or \
                docker_host.startswith(("unix://", "npipe://")):
            return
        cwd = os.getcwd()
        result = subprocess.run([
            "docker", "run", "--rm",
            "-v", f"{PROJECT_ROOT}:/devlab-project:ro",
            "-v", f"{cwd}:/devlab-cwd:ro",
            "alpine:3.20", "sh", "-c",
            "test -f /devlab-project/python/devlab.py && ls -A /devlab-cwd",
        ], capture_output=True, text=True)
        if result.returncode != 0 or sorted(result.stdout.split()) != sorted(os.listdir(cwd)):
            raise DevLabError(
                f"The Docker daemon at {docker_host} cannot see {PROJECT_ROOT} or {cwd} at the same "
                "path. Share the directory with the daemon (for example a volume mounted into both "
                "the job and the docker:dind service); see CI.md."
            )
        ContainerToolRunner._filesystem_checked = True
    
    def __init__(self):
        # Create shared kubeconfig directory
        self.shared_kubeconfig_dir = PROJECT_ROOT / ".kube"
        self.shared_kubeconfig_path = self.shared_kubeconfig_dir / "config"
        self.shared_kubeconfig_dir.mkdir(exist_ok=True)
        
        # Fallback to user's kubeconfig if shared doesn't exist
        self.kubeconfig_path = Path.home() / ".kube" / "config"
    
    def _prepare_volumes(self) -> Dict[str, Dict]:
        """Prepare volume mounts for containers"""
        volumes = {}
        
        # Use shared kubeconfig directory for both kind and kubectl
        volumes[str(self.shared_kubeconfig_dir)] = {"bind": "/root/.kube", "mode": "rw"}
        
        # Docker socket for kind
        volumes["/var/run/docker.sock"] = {"bind": "/var/run/docker.sock", "mode": "rw"}
        
        # Project directory
        volumes[str(PROJECT_ROOT)] = {"bind": "/workspace", "mode": "rw"}
        
        return volumes
    
    def kubectl(self, args: List[str], capture_output: bool = False, context: str = None, input: str = None, text: bool = False, tty: bool = False, publish: List[str] = ()) -> subprocess.CompletedProcess:
        """Run kubectl in container"""
        
        if args and args[0] == "apply":
            target = " ".join(str(arg) for arg in args[1:]) or "manifest from stdin"
            if target == "-f -":
                target = "generated manifest from stdin"
            console.print(f"[cyan]Applying Kubernetes resources: {target}[/cyan]")

        self._check_docker_filesystem()
        kubectl_image = self._ensure_kubectl_image()
        if kubectl_image is None:
            return subprocess.CompletedProcess([], 1, "", "Failed to build kubectl image")

        krew_dir = PROJECT_ROOT / ".krew"
        krew_dir.mkdir(exist_ok=True)

        cmd = [
            "docker", "run", "--rm", "-i",
            *(["-t"] if tty else []),
            *publish,
            "--network", "kind",  # Use kind network to communicate with KinD cluster
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",  # Use shared kubeconfig
            "-v", f"{krew_dir}:/root/.krew:rw",  # Persist krew index and plugins
            "-v", f"{os.getcwd()}:/workspace:rw",
            "-w", "/workspace",
            kubectl_image,
        ]
        
        # Add context if specified
        if context:
            cmd.extend(["--context", context])
        
        cmd.extend(args)
        
        return subprocess.run(cmd, capture_output=capture_output, text=text, input=input)

    def ensure_krew_plugins(self, quiet: bool = False) -> bool:
        """Install DEFAULT_KREW_PLUGINS into the persistent krew root once."""
        receipts_dir = PROJECT_ROOT / ".krew" / "receipts"
        missing = [
            plugin for plugin in DEFAULT_KREW_PLUGINS
            if not (receipts_dir / f"{plugin}.yaml").exists()
        ]
        if not missing:
            return True

        if not quiet:
            console.print(f"[blue]Installing krew plugins: {', '.join(missing)}[/blue]")
        for krew_args in (["krew", "update"], ["krew", "install", *missing]):
            result = self.kubectl(krew_args, capture_output=quiet, text=True)
            if result.returncode != 0:
                console.print(f"[red]kubectl {' '.join(krew_args)} failed[/red]")
                return False
        return True
    
    def helm(self, args: List[str], capture_output: bool = False, input: str = None, text: bool = False, quiet: bool = False) -> subprocess.CompletedProcess:
        """Run helm in container"""
        if args and not quiet:
            console.print(f"[cyan]Running Helm: {' '.join(str(arg) for arg in args)}[/cyan]")

        self._check_docker_filesystem()
        helm_image = self._ensure_helm_image()
        if helm_image is None:
            return subprocess.CompletedProcess([], 1, "", "Failed to build Helm image")

        helm_args = list(args)
        helm_state_dir = PROJECT_ROOT / ".helm"
        helm_config_dir = helm_state_dir / "config"
        helm_cache_dir = helm_state_dir / "cache"
        helm_data_dir = helm_state_dir / "data"
        for directory in (helm_config_dir, helm_cache_dir, helm_data_dir):
            directory.mkdir(parents=True, exist_ok=True)

        host_ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
        ca_file = "/etc/ssl/certs/devlab-ca-bundle.pem"
        host_ca_mount = []
        if host_ca_bundle.exists():
            ca_file = "/tmp/host-ca-certificates.crt"
            host_ca_mount = [
                "-v", f"{host_ca_bundle}:{ca_file}:ro",
            ]
        if len(helm_args) >= 2 and helm_args[:2] == ["repo", "add"]:
            helm_args.extend(["--ca-file", ca_file])

        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "kind",  # Use kind network to communicate with KinD cluster
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",  # Use shared kubeconfig
            "-v", f"{os.getcwd()}:/workspace:rw",
            "-w", "/workspace",
            "-v", f"{helm_config_dir}:/root/.config/helm:rw",
            "-v", f"{helm_state_dir}:/workspace/.helm:rw",
            "-v", f"{helm_cache_dir}:/root/.cache/helm:rw",
            "-v", f"{helm_data_dir}:/root/.local/share/helm:rw",
            *host_ca_mount,
            helm_image,
        ] + helm_args
        
        if not capture_output:
            return subprocess.run(cmd, text=text, input=input)

        if quiet:
            return subprocess.run(cmd, capture_output=True, text=text, input=input)

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
        )
        stdout_lines = []
        stderr_lines = []

        def stream_output(stream, lines, target):
            for line in iter(stream.readline, "" if text else b""):
                lines.append(line)
                target.write(line)
                target.flush()
            stream.close()

        stdout_thread = threading.Thread(
            target=stream_output, args=(process.stdout, stdout_lines, sys.stdout)
        )
        stderr_thread = threading.Thread(
            target=stream_output, args=(process.stderr, stderr_lines, sys.stderr)
        )
        stdout_thread.start()
        stderr_thread.start()

        if input is not None:
            process.stdin.write(input)
            process.stdin.close()
        return_code = process.wait()
        stdout_thread.join()
        stderr_thread.join()

        return subprocess.CompletedProcess(
            cmd,
            return_code,
            "".join(stdout_lines) if text else b"".join(stdout_lines),
            "".join(stderr_lines) if text else b"".join(stderr_lines),
        )
    
    def kind(self, args: List[str], capture_output: bool = False, quiet: bool = False) -> subprocess.CompletedProcess:
        """Run kind CLI - try host first, then local container image as fallback"""
        # First try to use host kind binary for better performance
        if shutil.which("kind"):
            # Host kind is available, but we need to ensure it uses our shared kubeconfig
            env = os.environ.copy()
            env["KUBECONFIG"] = str(self.shared_kubeconfig_path)
            cmd = ["kind"] + [str(arg) for arg in args]
            return subprocess.run(cmd, capture_output=capture_output, text=True, env=env)
        
        # Fallback: use local kind container image
        self._check_docker_filesystem()
        image_name = "devlab-kind:latest"
        
        # Check if our local kind image exists and matches the configured CLI version.
        try:
            result = subprocess.run(["docker", "image", "inspect", image_name], 
                                   capture_output=True, text=True)
            version_result = subprocess.run([
                "docker", "image", "inspect", image_name,
                "--format", "{{index .Config.Labels \"devlab.kind.version\"}}"
            ], capture_output=True, text=True)
            image_needs_build = (
                result.returncode != 0
                or version_result.returncode != 0
                or version_result.stdout.strip() != TOOL_VERSIONS["kind"]
            )
            if image_needs_build:
                if not quiet:
                    console.print("[blue]Building local KinD container image (version update)...[/blue]")
                self._build_kind_image(image_name)
        except Exception as e:
            if not quiet:
                console.print(f"[red]Error checking/building KinD image: {e}[/red]")
            return subprocess.CompletedProcess([], 1, "", str(e))
        
        if not quiet:
            console.print("[yellow]KinD not found on host, using local container image...[/yellow]")

        container_args = []
        for arg in args:
            if isinstance(arg, Path):
                try:
                    workspace_path = arg.relative_to(PROJECT_ROOT).as_posix()
                    container_args.append(f"/workspace/{workspace_path}")
                    continue
                except ValueError:
                    pass
            container_args.append(str(arg))
        
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "host",
            "-v", "/var/run/docker.sock:/var/run/docker.sock:rw",
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",
            "-v", f"{PROJECT_ROOT}:/workspace:rw",
            "-w", "/workspace",
            image_name
        ] + container_args
        
        return subprocess.run(cmd, capture_output=capture_output, text=True)
    
    def _build_kind_image(self, image_name: str):
        """Build the local KinD container image"""
        dockerfile_path = Path(__file__).parent / "Dockerfile.kind"
        
        if not dockerfile_path.exists():
            raise FileNotFoundError(f"Dockerfile.kind not found at {dockerfile_path}")
        
        target_arch = docker_architecture()

        build_cmd = [
            "docker", "build", 
            "-f", str(dockerfile_path),
            "-t", image_name,
            "--build-arg", f"KIND_VERSION={TOOL_VERSIONS['kind']}",
            "--build-arg", f"TARGETARCH={target_arch}",
            str(dockerfile_path.parent)
        ]
        
        console.print(f"[blue]Building {image_name} from {dockerfile_path}...[/blue]")
        result = subprocess.run(build_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            console.print(f"[red]Failed to build KinD image:[/red]")
            console.print(result.stderr)
            raise RuntimeError(f"Failed to build {image_name}")
        
        console.print(f"[green]Successfully built {image_name}[/green]")
    
    def _ensure_shared_kubeconfig(self):
        """Ensure shared kubeconfig exists, copy from user's if needed"""
        if not self.shared_kubeconfig_path.exists():
            user_kubeconfig = Path.home() / ".kube" / "config"
            if user_kubeconfig.exists():
                import shutil
                console.print("[blue]Copying user kubeconfig to shared location...[/blue]")
                shutil.copy2(user_kubeconfig, self.shared_kubeconfig_path)
            else:
                # Create an empty kubeconfig file
                self.shared_kubeconfig_path.write_text("apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: \"\"\nkind: Config\npreferences: {}\nusers: []\n")
    
    def _run_container(self, image: str, args: List[str], capture_output: bool = False, text: bool = False, input: str = None, context: str = None, use_kubeconfig: bool = True) -> subprocess.CompletedProcess:
        """Run a tool in a container with shared kubeconfig and kind network"""
        self._check_docker_filesystem()
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "kind",  # Use kind network to communicate with KinD cluster
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",  # Use shared kubeconfig
            "-v", f"{PROJECT_ROOT}:/workspace:rw",
            "-w", "/workspace",
        ]

        if "helm" in image:
            cmd.extend([
                "--entrypoint", "/bin/sh",
                "-v", f"{PROJECT_ROOT / 'python' / 'certs'}:/tmp/local-ca:ro",
            ])
        
        # Add user mapping for flux to read kubeconfig (flux runs as nobody:65534)
        if "flux" in image:
            cmd.extend(["-u", "root"])  # Run as root to access mounted kubeconfig
        
        cmd.append(image)

        if "helm" in image:
            cmd.extend([
                "-c",
                "set -e; bundle=/tmp/devlab-ca.pem; "
                "if [ -f /etc/ssl/cert.pem ]; then cat /etc/ssl/cert.pem > \"$bundle\"; "
                "elif [ -f /etc/ssl/certs/ca-certificates.crt ]; then cat /etc/ssl/certs/ca-certificates.crt > \"$bundle\"; "
                "else : > \"$bundle\"; fi; "
                "find /tmp/local-ca -type f -name '*.crt' -exec cat {} \\; >> \"$bundle\"; "
                "export SSL_CERT_FILE=\"$bundle\"; exec helm \"$@\"",
                "helm",
            ])
        
        # Add kubeconfig and context flags for linkerd and flux
        if use_kubeconfig and ("linkerd" in image or "flux" in image):
            cmd.extend(["--kubeconfig", "/root/.kube/config"])
            if context:
                cmd.extend(["--context", context])
            elif "flux" in image:
                cmd.extend(["--context", f"kind-{CLUSTER_NAME}"])
        
        cmd.extend(args)
        
        return subprocess.run(cmd, capture_output=capture_output, text=text, input=input)

    def _ensure_tool_image(self, image_name: str, dockerfile_name: str, build_args: Dict[str, str] = None) -> Optional[str]:
        """Build a cached tool image containing the current local CA bundle."""
        build_args = dict(build_args or {})
        dockerfile_path = Path(__file__).parent / dockerfile_name
        certificate_files = sorted((PROJECT_ROOT / "python" / "certs").rglob("*.crt"))
        digest = hashlib.sha256()
        digest.update(dockerfile_path.read_bytes())
        for key, value in sorted(build_args.items()):
            digest.update(f"{key}={value}".encode())
        for certificate in certificate_files:
            digest.update(certificate.relative_to(PROJECT_ROOT).as_posix().encode())
            digest.update(certificate.read_bytes())
        ca_bundle_version = digest.hexdigest()

        inspect_result = subprocess.run([
            "docker", "image", "inspect", image_name,
            "--format", "{{index .Config.Labels \"devlab.ca-bundle-version\"}}"
        ], capture_output=True, text=True)
        if inspect_result.returncode == 0 and inspect_result.stdout.strip() == ca_bundle_version:
            return image_name

        build_args["CA_BUNDLE_VERSION"] = ca_bundle_version
        console.print(f"[blue]Building local {image_name} image with custom CA certificates...[/blue]")
        build_result = subprocess.run([
            "docker", "build", "-f", str(dockerfile_path),
            "-t", image_name,
            *[arg for key, value in build_args.items() for arg in ("--build-arg", f"{key}={value}")],
            str(dockerfile_path.parent),
        ], capture_output=True, text=True)
        if build_result.returncode != 0:
            console.print(f"[red]Failed to build {image_name}:\n{build_result.stderr}[/red]")
            return None
        return image_name

    def _ensure_helm_image(self) -> Optional[str]:
        return self._ensure_tool_image("devlab-helm:latest", "Dockerfile.helm")

    def _ensure_kubectl_image(self) -> Optional[str]:
        try:
            target_arch = docker_architecture()
        except RuntimeError as error:
            console.print(f"[red]{error}[/red]")
            return None
        return self._ensure_tool_image("devlab-kubectl:latest", "Dockerfile.kubectl", {
            "KREW_VERSION": TOOL_VERSIONS["krew"],
            "TARGETARCH": target_arch,
        })
    
    def linkerd(self, args, capture_output=False, text=False, input=None, context=None):
        """Run linkerd CLI in container"""
        return self._run_container(
            image="cr.l5d.io/linkerd/cli-bin:stable-2.14.5",
            args=args,
            capture_output=capture_output,
            text=text,
            input=input,
            context=context
        )
    
    def flux(self, args, capture_output=False, text=False, input=None):
        """Run flux CLI in container"""
        return self._run_container(
            image="fluxcd/flux-cli:v2.3.0",
            args=args,
            capture_output=capture_output,
            text=text,
            input=input
        )

    def complete(self, tool: str, args: List[str]) -> subprocess.CompletedProcess:
        """Request shell completion candidates from a wrapped Cobra CLI."""
        completion_args = ["__complete", *args]
        if tool == "kubectl":
            return self.kubectl(completion_args, capture_output=True, text=True)
        if tool == "helm":
            return self.helm(completion_args, capture_output=True, text=True, quiet=True)
        if tool == "linkerd":
            return self._run_container(
                image="cr.l5d.io/linkerd/cli-bin:stable-2.14.5",
                args=completion_args,
                capture_output=True,
                text=True,
                use_kubeconfig=False,
            )
        if tool == "flux":
            return self.flux(completion_args, capture_output=True, text=True)
        if tool == "kind":
            return self.kind(completion_args, capture_output=True, quiet=True)
        raise ValueError(f"Unsupported completion tool: {tool}")

class DevLabManager:
    """Main class for managing dev-lab operations"""
    
    def __init__(self):
        self.tools = ContainerToolRunner()
        self.setup_logging()
    
    def setup_logging(self):
        """Configure logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def check_docker(self) -> bool:
        """Check if Docker is available and running"""
        try:
            client = docker.from_env()
            client.ping()
            return True
        except Exception as e:
            console.print(f"[red]Docker is not available: {e}[/red]")
            return False
    
    def bootstrap(self, monitoring: bool = None, krew: bool = None, gpu: bool = False) -> bool:
        """Bootstrap the complete dev-lab environment"""
        monitoring = profile_setting("monitoring") if monitoring is None else monitoring
        krew = profile_setting("krew") if krew is None else krew
        console.print(f"[bold blue]Bootstrapping Dev Lab Environment (profile: {ACTIVE_PROFILE})[/bold blue]")
        
        if not self.check_docker():
            return False

        if gpu and not self._check_gpu_prerequisites():
            return False
        
        # Ensure shared kubeconfig is available
        self.tools._ensure_shared_kubeconfig()
        
        # Create cluster
        if not self._create_cluster(gpu=gpu):
            return False

        if not self._configure_kind_node_certificates():
            return False

        # After the CA certificates: the node setup installs packages with apt
        if gpu and not self._setup_gpu_nodes():
            return False
        
        # Setup bootstrap infrastructure
        if not self._setup_registry():
            return False

        if not self._setup_metrics_server():
            return False

        if not self._setup_ingress():
            return False

        if monitoring and not self._deploy_monitoring():
            return False

        # After monitoring, so the DCGM exporter gets a ServiceMonitor
        if gpu and not self._setup_gpu_operator():
            return False

        if krew and not self.tools.ensure_krew_plugins():
            console.print("[yellow]Krew plugins were not installed; retry with ./devlab krew-sync[/yellow]")
        
        console.print("\n[bold green]Bootstrap completed successfully![/bold green]")
        show_access_points(monitoring)
        console.print("\n[bold blue]Useful Commands:[/bold blue]")
        console.print("  • [cyan]devlab status[/cyan] - Show environment status")
        console.print("  • [cyan]devlab build -t my-app:1 --push .[/cyan] - Build into the local registry")
        console.print("  • [cyan]devlab kubectl port-forward svc/<name> 8080:80[/cyan] - Ad hoc access on localhost:8080")
        console.print("  • [cyan]devlab deploy-gitops[/cyan] - Optional: let Flux manage workloads")
        if gpu:
            console.print("\n[bold blue]GPU Workloads:[/bold blue]")
            console.print("  • Request [cyan]nvidia.com/gpu[/cyan] in resource limits and set [cyan]runtimeClassName: nvidia[/cyan]")
            console.print("  • [cyan]devlab kubectl apply -f config/gpu/gpu-test-pod.yaml[/cyan] - GPU smoke test")
            console.print("  • Each GPU is time-sliced into shares: config/gpu/gpu-operator-values.yaml, then [cyan]devlab gpu-operator[/cyan]")
            console.print("  • Dask GPU workers: DASK-GPU-RUNBOOK.md")
        return True

    def _kind_nodes(self) -> List[str]:
        """Return the container names of the dev-lab KinD nodes."""
        result = subprocess.run([
            "docker", "ps", "--filter", f"label=io.x-k8s.kind.cluster={CLUSTER_NAME}",
            "--format", "{{.Names}}"
        ], capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[red]Could not list KinD nodes: {result.stderr.strip()}[/red]")
            return []
        return result.stdout.split()

    def _configure_kind_node_certificates(self) -> bool:
        """Install local CA certificates into all KinD nodes for containerd pulls."""
        certificate_dir = PROJECT_ROOT / "python" / "certs"
        certificates = list(certificate_dir.rglob("*.crt"))
        if not certificates:
            console.print("[yellow]No local CA certificates found; using node defaults[/yellow]")
            return True

        nodes = self._kind_nodes()
        if not nodes:
            console.print("[red]Could not find KinD nodes for CA installation[/red]")
            return False

        console.print(f"[blue]Installing {len(certificates)} custom CA certificate(s) into KinD nodes...[/blue]")
        for node in nodes:
            mkdir_result = subprocess.run([
                "docker", "exec", node, "mkdir", "-p",
                "/usr/local/share/ca-certificates/devlab"
            ], capture_output=True, text=True)
            if mkdir_result.returncode != 0:
                console.print(f"[red]Failed to prepare CA directory on {node}: {mkdir_result.stderr}[/red]")
                return False

            copy_result = subprocess.run([
                "docker", "cp", f"{certificate_dir}/.",
                f"{node}:/usr/local/share/ca-certificates/devlab/"
            ], capture_output=True, text=True)
            if copy_result.returncode != 0:
                console.print(f"[red]Failed to copy CA certificates to {node}: {copy_result.stderr}[/red]")
                return False

            update_result = subprocess.run([
                "docker", "exec", node, "sh", "-c",
                "find /usr/local/share/ca-certificates/devlab -type f -name '*.crt' -exec cp {} /usr/local/share/ca-certificates/ \\; && "
                "update-ca-certificates && (systemctl restart containerd || service containerd restart)"
            ], capture_output=True, text=True)
            if update_result.returncode != 0:
                console.print(f"[red]Failed to update containerd trust on {node}: {update_result.stderr}[/red]")
                return False

        console.print("[green]Custom CA certificates installed in KinD nodes[/green]")
        return True

    def _latest_kind_node_images(self, current_image: str):
        """Return the newest published KinD node image for each Kubernetes minor."""
        images = {}
        url = "https://registry.hub.docker.com/v2/repositories/kindest/node/tags"
        params = {"page_size": 100, "ordering": "last_updated"}
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
        system_ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
        if not ca_bundle and system_ca_bundle.exists():
            ca_bundle = str(system_ca_bundle)

        try:
            while url:
                response = requests.get(url, params=params, timeout=15, verify=ca_bundle or True)
                response.raise_for_status()
                payload = response.json()
                for tag in payload.get("results", []):
                    match = KIND_NODE_TAG_PATTERN.match(tag.get("name", ""))
                    if not match:
                        continue
                    version = tuple(int(part) for part in match.groups())
                    minor = version[:2]
                    if minor not in images or version > images[minor][0]:
                        images[minor] = (version, f"{KIND_NODE_REPOSITORY}:v{'.'.join(map(str, version))}")
                url = payload.get("next")
                params = None
        except (requests.RequestException, ValueError) as error:
            console.print(f"[yellow]Could not list latest KinD node images: {error}[/yellow]")

        current_match = re.match(r"^kindest/node:(v\d+\.\d+\.\d+)$", current_image)
        if current_match:
            version = tuple(int(part) for part in current_match.group(1)[1:].split("."))
            images.setdefault(version[:2], (version, current_image))

        return [image for _, image in sorted(images.values(), reverse=True)]

    def _select_kind_node_image(self, current_image: str):
        """Let the user keep the configured image or select a current minor release."""
        options = [f"Keep current: {current_image}"]
        options.extend(self._latest_kind_node_images(current_image))
        options = list(dict.fromkeys(options))

        if shutil.which("fzf"):
            result = subprocess.run(
                ["fzf", "--height=40%", "--layout=reverse", "--header=Select Kubernetes version"],
                input="\n".join(options),
                capture_output=True,
                text=True,
            )
            if result.returncode == 130:
                raise KeyboardInterrupt
            if result.returncode != 0:
                return current_image
            selection = result.stdout.strip()
        else:
            console.print("[blue]fzf is not installed; choose a Kubernetes version:[/blue]")
            selection = click.prompt("Selection", type=click.Choice(options), default=options[0])

        return current_image if selection.startswith("Keep current:") else selection
    
    def _create_cluster(self, gpu: bool = False) -> bool:
        """Create KinD cluster"""
        console.print("[blue]Creating KinD cluster...[/blue]")
        self.cluster_created = False
        gpu_config_file = None
        if gpu:
            # Also sets self.gpu_nodes, which the GPU node setup needs when an
            # existing cluster is kept
            gpu_config_file = self._gpu_cluster_config(PROJECT_ROOT / "cluster" / profile_setting("kind_config"))
        
        # Check if cluster already exists
        result = self.tools.kind(["get", "clusters"], capture_output=True)
        if CLUSTER_NAME in result.stdout:
            console.print(f"[yellow]Cluster '{CLUSTER_NAME}' already exists[/yellow]")
            if not interactive_session():
                console.print("[yellow]Non-interactive session: reusing the existing cluster[/yellow]")
                return True
            if not click.confirm("Delete and recreate?"):
                return True
            
            console.print("[blue]Deleting existing cluster...[/blue]")
            self.tools.kind(["delete", "cluster", "--name", CLUSTER_NAME])
        
        # Create cluster with config
        config_file = PROJECT_ROOT / "cluster" / profile_setting("kind_config")
        if not config_file.exists():
            console.print(f"[red]Kind config not found at {config_file}[/red]")
            return False

        config = yaml.safe_load(config_file.read_text()) or {}
        current_image = os.environ.get("DEVLAB_KIND_NODE_IMAGE") or config.get("image", DEFAULT_KIND_NODE_IMAGE)
        if interactive_session() and not os.environ.get("DEVLAB_KIND_NODE_IMAGE"):
            selected_image = self._select_kind_node_image(current_image)
        else:
            selected_image = current_image
        console.print(f"[blue]Using Kubernetes node image: {selected_image}[/blue]")
        if gpu_config_file:
            config_file = gpu_config_file
            workers = [f"{node} ({', '.join(devices)})" for node, devices in self.gpu_nodes.items()]
            console.print(f"[blue]GPU workers: {'; '.join(workers)}[/blue]")
        
        result = self.tools.kind([
            "create", "cluster", 
            "--config", config_file,
            "--image", selected_image,
            "--wait", "300s"
        ])
        
        if result.returncode != 0:
            console.print("[red]Failed to create cluster[/red]")
            return False
        self.cluster_created = True
        
        # Fix kubeconfig to use the container network IP
        if not self._fix_kubeconfig_for_containers():
            return False
        
        # Wait for nodes to be ready
        console.print("[blue]Waiting for nodes to be ready...[/blue]")
        self.tools.kubectl(["wait", "--for=condition=Ready", "nodes", "--all", "--timeout=300s"], context="kind-dev-lab")
        
        console.print("[green]Cluster created successfully[/green]")
        return True
    
    def _gpu_probe(self, *nvidia_smi_args: str) -> subprocess.CompletedProcess:
        """Run nvidia-smi in a container that gets every GPU the way kind nodes do."""
        return subprocess.run([
            "docker", "run", "--rm",
            "-v", f"/dev/null:{NVIDIA_DEVICES_DIR}/all",
            GPU_PROBE_IMAGE, "nvidia-smi", *nvidia_smi_args,
        ], capture_output=True, text=True)

    def _check_gpu_prerequisites(self) -> bool:
        """Check Docker can inject the host's GPUs into containers."""
        console.print("[blue]Checking GPU prerequisites...[/blue]")
        # The same /dev/null volume-mount injection the kind GPU nodes rely on
        result = self._gpu_probe("-L")
        if result.returncode != 0 or "GPU " not in result.stdout:
            console.print("[red]Docker cannot inject GPUs into containers: "
                          f"{(result.stderr or result.stdout).strip()}[/red]")
            console.print("[yellow]Needs a Linux Docker host with an NVIDIA GPU, its driver and the "
                          "NVIDIA Container Toolkit. Configure Docker for GPU-enabled kind (one-time):[/yellow]")
            console.print("  sudo nvidia-ctk runtime configure --runtime=docker --set-as-default --cdi.enabled")
            console.print("  sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place")
            console.print("  sudo systemctl restart docker")
            return False
        console.print(f"[green]GPUs visible to containers:[/green]\n{result.stdout.strip()}")
        self._check_vgpu_license()
        console.print("[green]GPU prerequisites met[/green]")
        return True

    def _check_vgpu_license(self) -> None:
        """Warn when a vGPU guest has no license (NVIDIA throttles it after 20 minutes)."""
        result = self._gpu_probe("-q")
        if result.returncode != 0:
            return
        # Only vGPU guests report a license status; bare-metal GPUs have none
        for status in re.findall(r"^\s*License Status\s*:\s*(.+?)\s*$", result.stdout, re.MULTILINE):
            if not status.startswith("Licensed"):
                console.print(f"[yellow]vGPU license status: {status}[/yellow]")
                console.print("[yellow]Unlicensed vGPUs are throttled after 20 minutes. "
                              "See the vGPU section of README.md to license this VM.[/yellow]")
                return

    def _host_gpu_count(self) -> int:
        result = self._gpu_probe("-L")
        return sum(1 for line in result.stdout.splitlines() if line.startswith("GPU "))

    def _gpu_cluster_config(self, base_config_file: Path) -> Path:
        """Write the profile's kind config with the GPU workers of cluster/gpu-workers.yaml."""
        workers_file = PROJECT_ROOT / "cluster" / "gpu-workers.yaml"
        base = yaml.safe_load(base_config_file.read_text()) or {}
        workers = (yaml.safe_load(workers_file.read_text()) or {}).get("workers")
        config, self.gpu_nodes = gpu_kind_config(base, workers)
        # Under the project, so the kind tool container sees it at /workspace
        generated = self.tools.shared_kubeconfig_dir / "kind-config.gpu.yaml"
        generated.write_text(
            f"# Generated by devlab bootstrap --gpu from cluster/{base_config_file.name}\n"
            "# and cluster/gpu-workers.yaml. Edit those instead.\n"
            + yaml.safe_dump(config, sort_keys=False)
        )
        return generated

    def _node_script(self, node: str, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "exec", node, "bash", "-c", script],
                              capture_output=True, text=True)

    def _modify_device_files_disabled(self, node: str) -> Optional[bool]:
        """Whether /proc/driver/nvidia/params in the node reads ModifyDeviceFiles: 0.

        Toolkit v1.19.0+ sets this up itself with a CDI hook; None when unknown.
        """
        result = subprocess.run(["docker", "exec", node, "cat", "/proc/driver/nvidia/params"],
                                capture_output=True, text=True)
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if line.strip() == "ModifyDeviceFiles: 0":
                return True
            if line.strip() == "ModifyDeviceFiles: 1":
                return False
        return None

    def _setup_gpu_nodes(self) -> bool:
        """Install the NVIDIA Container Toolkit and the nvidia containerd runtime in GPU nodes."""
        nodes = set(self._kind_nodes())
        host_gpus = None
        for node, devices in self.gpu_nodes.items():
            if node not in nodes:
                console.print(f"[red]GPU worker {node} is not part of the cluster[/red]")
                return False
            # A cluster kept from a bootstrap without --gpu has no GPUs in its nodes
            if subprocess.run(["docker", "exec", node, "nvidia-smi", "-L"],
                              capture_output=True, text=True).returncode != 0:
                console.print(f"[red]{node} has no GPUs: the existing cluster was not created with --gpu[/red]")
                console.print("[yellow]Delete it and re-bootstrap: ./devlab cleanup && ./devlab bootstrap --gpu[/yellow]")
                return False

            console.print(f"[blue]Setting up GPUs on {node} (devices: {', '.join(devices)})...[/blue]")
            for step, script in (("installing the NVIDIA Container Toolkit", INSTALL_TOOLKIT_SCRIPT),
                                 ("configuring containerd", CONFIGURE_RUNTIME_SCRIPT)):
                result = self._node_script(node, script)
                if result.returncode != 0:
                    output = (result.stdout + result.stderr).strip().splitlines()[-15:]
                    console.print(f"[red]Failed {step} on {node}:[/red]\n" + "\n".join(output))
                    return False

            # Failures from here on are warnings, like nvkind's benign umount
            # errors: the GPU capacity check catches a broken node
            masked = self._modify_device_files_disabled(node)
            if masked is None:
                console.print(f"[yellow]Could not read /proc/driver/nvidia/params on {node}[/yellow]")
            elif not masked and self._node_script(node, PATCH_PROC_DRIVER_SCRIPT).returncode != 0:
                console.print(f"[yellow]Could not mask /proc/driver/nvidia/params on {node}[/yellow]")

            # The node inherits every host /dev/nvidiaN; remove the ones it was not given
            if "all" in devices:
                continue
            if host_gpus is None:
                host_gpus = self._host_gpu_count()
            for index in range(host_gpus):
                if str(index) not in devices and \
                        self._node_script(node, REMOVE_DEVICE_NODE_SCRIPT.format(index=index)).returncode != 0:
                    console.print(f"[yellow]Could not remove /dev/nvidia{index} from {node}[/yellow]")

        console.print("[green]GPU nodes ready[/green]")
        return True

    def _setup_gpu_operator(self) -> bool:
        """Install the NVIDIA GPU Operator and wait until GPUs are allocatable."""
        console.print("[blue]Setting up NVIDIA GPU Operator...[/blue]")
        if not self._apply_manifest(CONFIG_DIR / "gpu" / "nvidia-runtimeclass.yaml"):
            return False
        if not self._ensure_namespace("gpu-operator"):
            return False
        # Operands run privileged
        self.tools.kubectl([
            "label", "namespace", "gpu-operator", "pod-security.kubernetes.io/enforce=privileged", "--overwrite"
        ], capture_output=True, context=f"kind-{CLUSTER_NAME}")

        extra_args = ["--wait", "--timeout", "600s"]
        if not self._has_service_monitor_crd():
            extra_args += ["--set", "dcgmExporter.serviceMonitor.enabled=false"]
        if not self._helm_release(
            "gpu-operator", "nvidia/gpu-operator", GPU_OPERATOR_CHART_VERSION, "gpu-operator",
            CONFIG_DIR / "gpu" / "gpu-operator-values.yaml",
            ("nvidia", "https://helm.ngc.nvidia.com/nvidia"),
            extra_args=extra_args,
        ):
            return False

        # NFD, the validator and then the device plugin start one after another
        console.print("[blue]Waiting for GPUs to be allocatable (up to 10 minutes)...[/blue]")
        for _ in range(300):
            result = self.tools.kubectl(["get", "nodes", "-o", "json"], capture_output=True, text=True,
                                        context=f"kind-{CLUSTER_NAME}")
            if result.returncode == 0:
                gpus = allocatable_gpus(result.stdout)
                if gpus:
                    for node, count in gpus.items():
                        console.print(f"[green]{node}: {count} allocatable nvidia.com/gpu[/green]")
                    console.print("[green]NVIDIA GPU Operator ready[/green]")
                    return True
            time.sleep(2)

        console.print("[red]No node advertised nvidia.com/gpu capacity[/red]")
        console.print("[yellow]Check: ./devlab kubectl get pods -n gpu-operator[/yellow]")
        console.print("[yellow]If you kept an existing cluster created without --gpu, delete it and "
                      "re-bootstrap: ./devlab cleanup && ./devlab bootstrap --gpu[/yellow]")
        return False

    def _fix_kubeconfig_for_containers(self) -> bool:
        """Fix kubeconfig to use container network IP instead of localhost"""
        console.print("[blue]Fixing kubeconfig for container networking...[/blue]")
        
        try:
            # Get the control plane container IP on the kind network
            client = docker.from_env()
            control_plane_container = client.containers.get(f"{CLUSTER_NAME}-control-plane")
            
            # Get the IP address on the kind network
            networks = control_plane_container.attrs['NetworkSettings']['Networks']
            if 'kind' not in networks:
                console.print("[red]Control plane container not on kind network[/red]")
                return False
            
            kind_ip = networks['kind']['IPAddress']
            console.print(f"[blue]Found control plane at {kind_ip} on kind network[/blue]")
            
            # Update the kubeconfig
            kubeconfig_path = self.tools.shared_kubeconfig_path
            with open(kubeconfig_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Find and update the kind-dev-lab cluster
            for cluster in config['clusters']:
                if cluster['name'] == f'kind-{CLUSTER_NAME}':
                    old_server = cluster['cluster']['server']
                    cluster['cluster']['server'] = f'https://{kind_ip}:6443'
                    console.print(f"[blue]Updated server from {old_server} to https://{kind_ip}:6443[/blue]")
                    break
            
            # Write back the updated config
            with open(kubeconfig_path, 'w') as f:
                yaml.safe_dump(config, f, default_flow_style=False)
            
            console.print("[green]Kubeconfig updated for container networking[/green]")
            return True
            
        except Exception as e:
            console.print(f"[red]Failed to fix kubeconfig: {e}[/red]")
            return False
    
    def _setup_linkerd(self) -> bool:
        """Setup Linkerd service mesh"""
        console.print("[blue]Setting up Linkerd service mesh...[/blue]")
        
        # Install Gateway API CRDs
        console.print("[blue]Installing Gateway API CRDs...[/blue]")
        result = self.tools.kubectl([
            "apply", "-f", 
            "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml"
        ], context="kind-dev-lab")
        
        if result.returncode != 0:
            console.print("[red]Failed to install Gateway API CRDs[/red]")
            return False
        
        # Wait for CRDs
        self.tools.kubectl([
            "wait", "--for", "condition=established", "--timeout=60s",
            "crd/gateways.gateway.networking.k8s.io"
        ])
        
        # Check Linkerd pre-flight
        result = self.tools.linkerd(["check", "--pre"], capture_output=True, context=f"kind-{CLUSTER_NAME}")
        if result.returncode != 0:
            console.print(f"[red]Linkerd pre-flight checks failed:\n{result.stdout}[/red]")
            console.print(f"[red]Error output: {result.stderr}[/red]")
            return False
        
        # Install Linkerd CRDs
        console.print("[blue]Installing Linkerd CRDs...[/blue]")
        crds_result = self.tools.linkerd(["install", "--crds"], capture_output=True, text=True, context=f"kind-{CLUSTER_NAME}")
        if crds_result.returncode == 0:
            self.tools.kubectl(["apply", "-f", "-"], input=crds_result.stdout, text=True, context=f"kind-{CLUSTER_NAME}")
        
        # Install Linkerd control plane
        console.print("[blue]Installing Linkerd control plane...[/blue]")
        install_result = self.tools.linkerd(["install"], capture_output=True, text=True, context=f"kind-{CLUSTER_NAME}")
        if install_result.returncode == 0:
            self.tools.kubectl(["apply", "-f", "-"], input=install_result.stdout, text=True, context=f"kind-{CLUSTER_NAME}")
        
        # Wait for Linkerd to be ready
        self.tools.kubectl([
            "wait", "--for=condition=available", "deployment", 
            "-n", "linkerd", "--all", "--timeout=300s"
        ])
        
        # Install Linkerd Viz
        console.print("[blue]Installing Linkerd Viz...[/blue]")
        viz_result = self.tools.linkerd(["viz", "install"], capture_output=True, text=True, context=f"kind-{CLUSTER_NAME}")
        if viz_result.returncode == 0:
            self.tools.kubectl(["apply", "-f", "-"], input=viz_result.stdout, text=True, context=f"kind-{CLUSTER_NAME}")
        
        # Wait for Viz to be ready
        self.tools.kubectl([
            "wait", "--for=condition=available", "deployment",
            "-n", "linkerd-viz", "--all", "--timeout=300s"
        ], context=f"kind-{CLUSTER_NAME}")
        
        console.print("[green]Linkerd setup completed[/green]")
        return True
    
    def _setup_registry(self) -> bool:
        """Setup local container registry"""
        console.print("[blue]Setting up local container registry...[/blue]")

        for image in ["registry:2.8", "joxit/docker-registry-ui:2.5.7"]:
            if not self._load_kind_image(image):
                return False
        
        if not self._ensure_namespace("dev-lab-registry"):
            return False

        # Clusters created before the registry became a single Deployment ran
        # it as a DaemonSet, which would hold hostPort 5000.
        self.tools.kubectl([
            "delete", "daemonset", "docker-registry", "-n", "dev-lab-registry",
            "--ignore-not-found"
        ], context=f"kind-{CLUSTER_NAME}")

        for manifest in ["registry.yaml", "registry-ui.yaml"]:
            if not self._apply_manifest(CONFIG_DIR / "registry" / manifest):
                return False

        result = self.tools.kubectl([
            "rollout", "status", "deployment/docker-registry",
            "-n", "dev-lab-registry", "--timeout=300s"
        ], context=f"kind-{CLUSTER_NAME}")
        if result.returncode != 0:
            console.print("[red]Registry did not become ready[/red]")
            console.print("[yellow]Registry pod diagnostics:[/yellow]")
            self.tools.kubectl([
                "get", "pods", "-n", "dev-lab-registry", "-o", "wide"
            ])
            self.tools.kubectl([
                "get", "events", "-n", "dev-lab-registry", "--sort-by=.lastTimestamp"
            ])
            return False
        console.print("[green]Registry setup completed[/green]")
        return True

    def _ensure_namespace(self, namespace: str) -> bool:
        """Create a namespace, or leave an existing one in place."""
        namespace_result = self.tools.kubectl([
            "create", "namespace", namespace, "--dry-run=client", "-o", "yaml"
        ], capture_output=True, text=True, context=f"kind-{CLUSTER_NAME}")
        if namespace_result.returncode != 0:
            console.print(f"[red]Failed to generate namespace {namespace}[/red]")
            return False
        result = self.tools.kubectl(
            ["apply", "-f", "-"], input=namespace_result.stdout, text=True,
            context=f"kind-{CLUSTER_NAME}"
        )
        if result.returncode != 0:
            console.print(f"[red]Failed to ensure namespace {namespace}[/red]")
            return False
        return True

    def _apply_manifest(self, manifest: Path) -> bool:
        """Apply a manifest from the project through kubectl's stdin."""
        if not manifest.exists():
            console.print(f"[red]Manifest not found at {manifest}[/red]")
            return False
        console.print(f"[cyan]Applying {manifest.relative_to(PROJECT_ROOT)}[/cyan]")
        result = self.tools.kubectl(
            ["apply", "-f", "-"], input=manifest.read_text(), text=True,
            context=f"kind-{CLUSTER_NAME}"
        )
        if result.returncode != 0:
            console.print(f"[red]Failed to apply {manifest.name}[/red]")
            return False
        return True

    def _kind_node_platform(self, node: str) -> Optional[str]:
        """Return the OCI platform (linux/amd64, linux/arm64, ...) of a KinD node."""
        result = subprocess.run(["docker", "exec", node, "uname", "-m"], capture_output=True, text=True)
        architecture = DOCKER_ARCHITECTURES.get(result.stdout.strip())
        if result.returncode != 0 or not architecture:
            console.print(f"[red]Could not determine KinD node architecture: {result.stderr.strip()}[/red]")
            return None
        return f"linux/{architecture}"

    def _load_kind_image(self, image: str) -> bool:
        """Ensure an image is available in every KinD node without node-side pulls.

        With Docker's containerd image store, `docker save` (and `kind load`)
        exports the whole multi-platform index, including platforms that were
        never pulled, and the node-side import fails on the missing blobs.
        Pulling and saving only the node platform avoids that on amd64 and
        arm64 hosts alike.
        """
        nodes = self._kind_nodes()
        if not nodes:
            console.print("[red]Could not find KinD nodes for image import[/red]")
            return False
        platform = self._kind_node_platform(nodes[0])
        if platform is None:
            return False

        console.print(f"[blue]Pulling {image} ({platform}) through the host Docker daemon...[/blue]")
        pull_result = subprocess.run(["docker", "pull", "--quiet", "--platform", platform, image])
        if pull_result.returncode != 0:
            inspect_result = subprocess.run(["docker", "image", "inspect", image], capture_output=True)
            if inspect_result.returncode != 0:
                console.print(f"[red]Failed to pull {image}[/red]")
                return False
            console.print(f"[yellow]Pull failed; using cached host image {image}[/yellow]")

        save_result = subprocess.run(["docker", "save", "--platform", platform, image], capture_output=True)
        if save_result.returncode != 0 and b"unknown flag" in save_result.stderr:
            # Docker < 28 has no `save --platform`; its classic image store
            # holds only the pulled platform, so a plain save is equivalent.
            save_result = subprocess.run(["docker", "save", image], capture_output=True)
        if save_result.returncode != 0:
            console.print(f"[red]Failed to save {image} from the host Docker daemon: {save_result.stderr.decode(errors='replace')}[/red]")
            return False

        console.print(f"[blue]Importing {image} into KinD nodes...[/blue]")
        for node in nodes:
            import_result = subprocess.run([
                "docker", "exec", "--privileged", "-i", node,
                "ctr", "--namespace=k8s.io", "images", "import",
                "--platform", platform, "--digests", "--snapshotter=overlayfs", "-"
            ], input=save_result.stdout, capture_output=True)
            if import_result.returncode != 0:
                console.print(f"[red]Image import failed on {node}: {import_result.stderr.decode(errors='replace')}[/red]")
                return False
        return True

    def _helm_release(self, release: str, chart: str, version: str, namespace: str,
                      values_file: Path, repo: tuple, values_text: str = None,
                      extra_args: List[str] = ()) -> bool:
        """Install or upgrade a Helm release from a (name, url) chart repository."""
        repo_name, repo_url = repo
        for command in [
            ["repo", "add", "--force-update", repo_name, repo_url],
            ["repo", "update", repo_name],
        ]:
            result = self.tools.helm(command, capture_output=True, text=True, quiet=True)
            if result.returncode != 0:
                console.print(f"[red]Helm command failed: {' '.join(command)}\n{result.stderr}[/red]")
                return False

        result = self.tools.helm([
            "upgrade", "--install", release, chart,
            "--version", version,
            "--namespace", namespace, "--create-namespace",
            "--values", "-",
            *extra_args,
        ], input=values_text if values_text is not None else values_file.read_text(), text=True)
        if result.returncode != 0:
            console.print(f"[red]Failed to install Helm release {release}[/red]")
            return False
        return True

    def _rollout_status(self, namespace: str, *resources: str) -> bool:
        for resource in resources:
            result = self.tools.kubectl([
                "rollout", "status", resource, "-n", namespace, "--timeout=300s"
            ], context=f"kind-{CLUSTER_NAME}")
            if result.returncode != 0:
                console.print(f"[red]{resource} in {namespace} did not become ready[/red]")
                return False
        return True

    def _setup_ingress(self) -> bool:
        """Install the Traefik ingress controller on the control-plane node."""
        console.print("[blue]Setting up Traefik ingress controller...[/blue]")
        if not self._helm_release(
            "traefik", "traefik/traefik", TRAEFIK_CHART_VERSION, "traefik",
            CONFIG_DIR / "ingress" / "traefik-values.yaml",
            ("traefik", "https://traefik.github.io/charts"),
        ):
            return False
        if not self._rollout_status("traefik", "deployment/traefik"):
            return False
        console.print("[green]Traefik ingress controller ready on http://*.localhost[/green]")
        return True

    # Addons: optional components installed with `devlab addon enable <name>`

    def addon_installed(self, name: str) -> bool:
        release, namespace = ADDONS[name]["release"]
        result = self.tools.helm(
            ["status", release, "-n", namespace], capture_output=True, text=True, quiet=True
        )
        return result.returncode == 0

    def enable_addon(self, name: str) -> bool:
        console.print(f"[bold blue]Enabling addon {name}[/bold blue]")
        if not getattr(self, ADDONS[name]["enable"])():
            return False
        console.print(f"[green]Addon {name} enabled[/green]")
        return True

    def disable_addon(self, name: str) -> bool:
        console.print(f"[bold blue]Disabling addon {name}[/bold blue]")
        if not getattr(self, ADDONS[name]["disable"])():
            return False
        console.print(f"[green]Addon {name} disabled[/green]")
        return True

    def _has_service_monitor_crd(self) -> bool:
        """True when the Prometheus operator (monitoring stack) is installed."""
        return self.tools.kubectl(
            ["get", "crd", "servicemonitors.monitoring.coreos.com"], capture_output=True
        ).returncode == 0

    def _enable_keda(self) -> bool:
        no_monitoring = [] if self._has_service_monitor_crd() else [
            "--set", "prometheus.metricServer.serviceMonitor.enabled=false",
            "--set", "prometheus.operator.serviceMonitor.enabled=false",
        ]
        if not self._helm_release(
            "keda", "kedacore/keda", KEDA_CHART_VERSION, "keda",
            CONFIG_DIR / "addons" / "keda" / "values.yaml",
            ("kedacore", "https://kedacore.github.io/charts"),
            extra_args=no_monitoring,
        ):
            return False
        return self._rollout_status(
            "keda", "deployment/keda-operator", "deployment/keda-operator-metrics-apiserver",
            "deployment/keda-admission-webhooks",
        )

    def _disable_keda(self) -> bool:
        # ScaledObjects hold finalizers that need the operator; remove them first
        self.tools.kubectl(["delete", "scaledobjects,scaledjobs", "-A", "--all", "--wait=true"])
        result = self.tools.helm(["uninstall", "keda", "-n", "keda", "--wait", "--ignore-not-found"])
        return result.returncode == 0

    def _kubernetes_minor(self) -> Optional[tuple]:
        result = self.tools.kubectl(["version", "-o", "json"], capture_output=True, text=True)
        if result.returncode != 0:
            console.print("[red]Could not read the Kubernetes server version[/red]")
            return None
        server = json.loads(result.stdout)["serverVersion"]
        return int(server["major"]), int(re.match(r"\d+", server["minor"]).group())

    def _enable_node_autoscaler(self) -> bool:
        minor = self._kubernetes_minor()
        if minor is None:
            return False
        image_tag = CLUSTER_AUTOSCALER_IMAGE_TAGS.get(minor)
        if image_tag is None:
            nearest = max(key for key in CLUSTER_AUTOSCALER_IMAGE_TAGS if key <= minor) \
                if any(key <= minor for key in CLUSTER_AUTOSCALER_IMAGE_TAGS) \
                else min(CLUSTER_AUTOSCALER_IMAGE_TAGS)
            image_tag = CLUSTER_AUTOSCALER_IMAGE_TAGS[nearest]
            console.print(f"[yellow]No cluster-autoscaler pinned for Kubernetes {minor[0]}.{minor[1]}; using {image_tag}[/yellow]")

        nodes = self._kind_nodes()
        platform = self._kind_node_platform(nodes[0]) if nodes else None
        if platform is None:
            return False

        # KWOK simulates the kubelets of the nodes cluster-autoscaler creates.
        # Server-side apply: the CRDs are too large for the last-applied annotation.
        release_url = f"https://github.com/kubernetes-sigs/kwok/releases/download/{KWOK_VERSION}"
        for manifest in ["kwok.yaml", "stage-fast.yaml"]:
            result = self.tools.kubectl(
                ["apply", "--server-side", "--force-conflicts", "-f", f"{release_url}/{manifest}"],
                context=f"kind-{CLUSTER_NAME}",
            )
            if result.returncode != 0:
                console.print(f"[red]Failed to install KWOK {manifest}[/red]")
                return False
        if not self._rollout_status("kube-system", "deployment/kwok-controller"):
            return False

        # The chart ships sample node templates in this ConfigMap, and devlab
        # replaces them below. Delete it first so the upgrade recreates it
        # instead of conflicting with devlab's copy (Helm 4 server-side apply).
        self.tools.kubectl([
            "delete", "configmap", "kwok-provider-templates", "-n", "kube-system", "--ignore-not-found"
        ], capture_output=True)
        if not self._helm_release(
            "cluster-autoscaler", "autoscaler/cluster-autoscaler", CLUSTER_AUTOSCALER_CHART_VERSION,
            "kube-system", CONFIG_DIR / "addons" / "node-autoscaler" / "cluster-autoscaler-values.yaml",
            ("autoscaler", "https://kubernetes.github.io/autoscaler"),
            extra_args=["--set", f"image.tag={image_tag}",
                        *([] if self._has_service_monitor_crd() else ["--set", "serviceMonitor.enabled=false"])],
        ):
            return False

        # The chart always ships sample node templates; replace them with ours
        templates = (CONFIG_DIR / "addons" / "node-autoscaler" / "kwok-provider.yaml").read_text()
        result = self.tools.kubectl(
            ["apply", "--server-side", "--force-conflicts", "--field-manager=devlab", "-f", "-"],
            input=templates.replace("${ARCH}", platform.split("/")[1]),
            text=True, context=f"kind-{CLUSTER_NAME}",
        )
        if result.returncode != 0:
            console.print("[red]Failed to apply the kwok node templates[/red]")
            return False
        # The provider reads its ConfigMaps only at startup
        self.tools.kubectl([
            "rollout", "restart", "deployment/cluster-autoscaler", "-n", "kube-system"
        ], capture_output=True)
        return self._rollout_status("kube-system", "deployment/cluster-autoscaler")

    def _disable_node_autoscaler(self) -> bool:
        result = self.tools.helm([
            "uninstall", "cluster-autoscaler", "-n", "kube-system", "--wait", "--ignore-not-found"
        ])
        if result.returncode != 0:
            return False
        # Fake nodes outlive cluster-autoscaler; their pods go back to Pending
        self.tools.kubectl(["delete", "nodes", "-l", "devlab.io/node-pool=kwok", "--ignore-not-found"])
        release_url = f"https://github.com/kubernetes-sigs/kwok/releases/download/{KWOK_VERSION}"
        for manifest in ["stage-fast.yaml", "kwok.yaml"]:
            self.tools.kubectl(["delete", "--ignore-not-found", "-f", f"{release_url}/{manifest}"])
        return True
    
    def _setup_metrics_server(self) -> bool:
        """Setup metrics server"""
        console.print("[blue]Setting up metrics server...[/blue]")
        
        # Install metrics server
        result = self.tools.kubectl([
            "apply", "-f", 
            "https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml"
        ], context=f"kind-{CLUSTER_NAME}")
        if result.returncode != 0:
            console.print("[red]Failed to install metrics server[/red]")
            return False
        
        # Patch for KinD only when the argument is not already present.
        args_result = self.tools.kubectl([
            "get", "deployment", "metrics-server", "-n", "kube-system",
            "-o", "jsonpath={.spec.template.spec.containers[0].args}"
        ], capture_output=True, text=True, context=f"kind-{CLUSTER_NAME}")
        if args_result.returncode != 0:
            console.print("[red]Failed to inspect metrics server configuration[/red]")
            return False

        if "--kubelet-insecure-tls" not in args_result.stdout:
            patch = '[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
            result = self.tools.kubectl([
                "patch", "deployment", "metrics-server", "-n", "kube-system",
                "--type=json", f"--patch={patch}"
            ], context=f"kind-{CLUSTER_NAME}")
            if result.returncode != 0:
                console.print("[red]Failed to configure metrics server[/red]")
                return False
        
        # Wait for metrics server
        result = self.tools.kubectl([
            "wait", "--for=condition=available", "deployment/metrics-server",
            "-n", "kube-system", "--timeout=300s"
        ], context=f"kind-{CLUSTER_NAME}")
        if result.returncode != 0:
            console.print("[red]Metrics server did not become ready[/red]")
            return False
        
        console.print("[green]Metrics server setup completed[/green]")
        return True
    
    def _check_bootstrap(self) -> bool:
        """Check if bootstrap was completed"""
        console.print("[blue]Checking bootstrap prerequisites...[/blue]")
        
        # Check cluster
        result = self.tools.kubectl(["cluster-info", "--context", f"kind-{CLUSTER_NAME}"], capture_output=True)
        if result.returncode != 0:
            console.print("[red]dev-lab cluster not found or not accessible[/red]")
            return False
        
        # Check registry
        result = self.tools.kubectl([
            "get", "pods", "-n", "dev-lab-registry", 
            "-l", "app=docker-registry", "--field-selector=status.phase=Running"
        ], capture_output=True)
        if result.returncode != 0:
            console.print("[red]Local registry not running[/red]")
            return False
        
        console.print("[green]Bootstrap prerequisites verified[/green]")
        return True
    
    def _deploy_monitoring(self) -> bool:
        """Deploy monitoring stack"""
        console.print("[blue]Deploying monitoring stack...[/blue]")
        
        # Add Helm repositories
        for repository in [
            ["repo", "add", "--force-update", "prometheus-community", "https://prometheus-community.github.io/helm-charts"],
            ["repo", "add", "--force-update", "grafana", "https://grafana.github.io/helm-charts"],
            ["repo", "update"],
        ]:
            result = self.tools.helm(repository, capture_output=True, text=True)
            if result.returncode != 0:
                console.print(f"[red]Helm command failed: {' '.join(repository)}\n{result.stderr}[/red]")
                return False
        
        # Create monitoring namespace
        namespace_result = self.tools.kubectl([
            "create", "namespace", "monitoring", 
            "--dry-run=client", "-o", "yaml"
        ], capture_output=True, text=True)
        if namespace_result.returncode != 0:
            console.print("[red]Failed to generate monitoring namespace[/red]")
            return False

        result = self.tools.kubectl(["apply", "-f", "-"], input=namespace_result.stdout, text=True)
        if result.returncode != 0:
            console.print("[red]Failed to create monitoring namespace[/red]")
            return False
        
        # Install Prometheus stack
        values_file = CONFIG_DIR / "monitoring" / "prometheus-values.yaml"
        if not values_file.exists():
            console.print(f"[red]Prometheus values not found at {values_file}[/red]")
            return False
        workdir=os.getcwd()
        os.chdir(CONFIG_DIR / "monitoring")
        result = self.tools.helm([
            "upgrade", "--install", "kube-prometheus-stack",
            "prometheus-community/kube-prometheus-stack",
            "--namespace", "monitoring",
            "--values", "prometheus-values.yaml"
        ])
        os.chdir(workdir)
        if result.returncode != 0:
            console.print("[red]Failed to install monitoring Helm chart[/red]")
            return False
        
        # Wait for all pods belonging to the Helm release. Component-specific
        # names vary across chart versions, while the release label is stable.
        # Grafana has no release label, and Prometheus/Alertmanager pods are
        # created later by the operator, so wait for those explicitly too.
        waits = [
            ["wait", "--for=condition=ready", "pod", "-l", "release=kube-prometheus-stack"],
            ["rollout", "status", "deployment/kube-prometheus-stack-grafana"],
            ["wait", "--for=condition=Available",
             "prometheus/kube-prometheus-stack-prometheus",
             "alertmanager/kube-prometheus-stack-alertmanager"],
        ]
        result = subprocess.CompletedProcess([], 0)
        for wait in waits:
            result = self.tools.kubectl([*wait, "-n", "monitoring", "--timeout=300s"])
            if result.returncode != 0:
                break
        if result.returncode != 0:
            console.print("[red]Monitoring stack did not become ready[/red]")
            console.print("[yellow]Monitoring pod diagnostics:[/yellow]")
            self.tools.kubectl([
                "get", "pods", "-n", "monitoring", "-o", "wide"
            ])
            self.tools.kubectl([
                "get", "events", "-n", "monitoring", "--sort-by=.lastTimestamp"
            ])
            return False
        
        console.print("[green]Monitoring stack deployed[/green]")
        return True
    
    def deploy_gitops(self) -> bool:
        """Deploy using GitOps method with Flux CD"""
        console.print("[bold blue]GitOps Deployment[/bold blue]")
        
        if not self._check_bootstrap():
            return False
        
        # Install Flux controllers
        if not self._install_flux_controllers():
            return False
        
        # Generate SSH deploy key
        if not self._generate_deploy_key():
            return False
        
        # Create Flux secret
        if not self._create_flux_secret():
            return False
        
        # Show deploy key for GitHub setup
        self._show_deploy_key()
        
        # Create Git source
        if not self._create_git_source():
            return False
        
        # Apply Git-managed kustomizations
        if not self._apply_git_kustomizations():
            return False
        
        # Wait for deployment and show status
        self._wait_for_gitops_deployment()
        self._show_gitops_info()
        return True
    
    def _install_flux_controllers(self) -> bool:
        """Install Flux controllers"""
        console.print("[blue]Installing Flux controllers...[/blue]")
        
        # Check if flux-system namespace already exists
        result = self.tools.kubectl(["get", "ns", "flux-system"], capture_output=True)
        if result.returncode == 0:
            console.print("[yellow]Flux controllers may already be installed[/yellow]")
            result = self.tools.kubectl(["get", "deployment", "-n", "flux-system", "source-controller"], capture_output=True)
            if result.returncode == 0:
                console.print("[green]Flux controllers already installed[/green]")
                return True
        
        # Install Flux controllers
        result = self.tools.flux(["install"])
        if result.returncode != 0:
            console.print("[red]Failed to install Flux controllers[/red]")
            return False
        
        # Wait for controllers to be ready
        console.print("[blue]Waiting for Flux controllers to be ready...[/blue]")
        self.tools.kubectl([
            "wait", "--for=condition=available", "deployment", "--all", 
            "-n", "flux-system", "--timeout=300s"
        ])
        
        console.print("[green]Flux controllers installed and ready[/green]")
        return True
    
    def _generate_deploy_key(self) -> bool:
        """Generate SSH deploy key for GitOps"""
        console.print("[blue]Setting up SSH deploy key...[/blue]")
        
        # Remove existing keys
        if Path(KEY_PATH).exists():
            console.print("[yellow]Deploy key already exists. Removing old key...[/yellow]")
            Path(KEY_PATH).unlink(missing_ok=True)
            Path(f"{KEY_PATH}.pub").unlink(missing_ok=True)
        
        # Generate new SSH key pair
        console.print("[blue]Generating new SSH key pair...[/blue]")
        result = subprocess.run([
            "ssh-keygen", "-t", "ed25519", "-f", KEY_PATH, "-N", "", 
            "-C", f"flux-dev-lab-{time.strftime('%Y%m%d')}"
        ], capture_output=True, text=True)
        
        if result.returncode != 0 or not Path(KEY_PATH).exists():
            console.print("[red]Failed to generate SSH key[/red]")
            return False
        
        console.print("[green]SSH key pair generated[/green]")
        return True
    
    def _create_flux_secret(self) -> bool:
        """Create Flux system secret with SSH deploy key"""
        console.print("[blue]Creating flux-system secret with SSH deploy key...[/blue]")
        
        # Delete existing secret if it exists
        self.tools.kubectl([
            "delete", "secret", "dev-lab-repo", "-n", "flux-system", "--ignore-not-found=true"
        ])
        
        # Get GitHub known hosts
        result = subprocess.run(["ssh-keyscan", "github.com"], capture_output=True, text=True)
        if result.returncode != 0:
            console.print("[red]Failed to get GitHub known hosts[/red]")
            return False
        
        known_hosts = result.stdout.strip()
        
        # Create new secret with SSH key
        # Use workspace paths that are accessible inside the container
        key_path_container = "/workspace/flux-deploy-key"
        result = self.tools.kubectl([
            "create", "secret", "generic", "dev-lab-repo",
            f"--from-file=identity={key_path_container}",
            f"--from-file=identity.pub={key_path_container}.pub",
            f"--from-literal=known_hosts={known_hosts}",
            "-n", "flux-system"
        ])
        
        if result.returncode != 0:
            console.print("[red]Failed to create flux-system secret[/red]")
            return False
        
        # Label the secret
        self.tools.kubectl([
            "label", "secret", "dev-lab-repo", "-n", "flux-system", 
            "app.kubernetes.io/part-of=flux"
        ])
        
        console.print("[green]dev-lab-repo secret created[/green]")
        return True
    
    def _show_deploy_key(self):
        """Display deploy key for GitHub setup"""
        console.print("\n[bold blue]GitHub Deploy Key Setup[/bold blue]\n")
        
        console.print("[cyan]Add this public key as a deploy key to your GitHub repository:[/cyan]")
        console.print(f"[cyan]Repository:[/cyan] https://github.com/jbotstevens/notes")
        console.print(f"[cyan]Settings → Deploy keys → Add deploy key[/cyan]\n")
        
        console.print("[yellow]Public Key:[/yellow]")
        console.print("─" * 50)
        with open(f"{KEY_PATH}.pub", "r") as f:
            console.print(f.read().strip())
        console.print("─" * 50)
        
        console.print("\n[yellow] Make sure to:[/yellow]")
        console.print(f"  1. Give the key a descriptive title (e.g., 'flux-dev-lab-{time.strftime('%Y%m%d')}')")  
        console.print("  2. Paste the public key above")
        console.print("  3. Leave 'Allow write access' UNCHECKED (read-only)")
        console.print("  4. Click 'Add key'")
        
        input("\n[blue]Press Enter when you've added the deploy key to GitHub...[/blue]")
    
    def _create_git_source(self) -> bool:
        """Create GitRepository source"""
        console.print("[blue]Creating Git source...[/blue]")
        
        # Read the template and update repository URL
        git_repo_config = CONFIG_DIR / "gitops" / "git-repository.yaml"
        if not git_repo_config.exists():
            console.print(f"[red]Git repository config not found at {git_repo_config}[/red]")
            return False
        
        # Update the repository URL and apply
        result = subprocess.run([
            "sed", f"s|url: ssh://git@github.com/jbotstevens/notes.git|url: {REPO_URL}|",
            str(git_repo_config)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            console.print("[red]Failed to process git repository config[/red]")
            return False
        
        # Apply the configuration
        apply_result = self.tools.kubectl(["apply", "-f", "-"], input=result.stdout, text=True)
        if apply_result.returncode != 0:
            console.print("[red]Failed to create GitRepository[/red]")
            return False
        
        # Wait for GitRepository to sync
        console.print("[blue]Waiting for GitRepository to sync...[/blue]")
        time.sleep(10)
        
        result = self.tools.kubectl([
            "wait", "--for=condition=ready", "gitrepository", "dev-lab-repo", 
            "-n", "flux-system", "--timeout=120s"
        ], capture_output=True)
        
        if result.returncode == 0:
            console.print("[green]GitRepository synced successfully[/green]")
        else:
            console.print("[yellow] GitRepository may not be ready yet. Continuing...[/yellow]")
        
        return True
    
    def _apply_git_kustomizations(self) -> bool:
        """Apply Git-managed kustomizations"""
        console.print("[blue]Applying Git-managed kustomizations...[/blue]")
        
        # Apply the cluster-specific kustomizations
        kustomizations_file = PROJECT_ROOT / "clusters" / "dev-lab" / "dev-lab-kustomizations.yaml"
        if not kustomizations_file.exists():
            console.print(f"[yellow] Kustomizations file not found at {kustomizations_file}[/yellow]")
            console.print("[yellow]GitOps setup complete, but manual kustomizations not applied[/yellow]")
            return True
        
        result = self.tools.kubectl(["apply", "-f", "/workspace/clusters/dev-lab/dev-lab-kustomizations.yaml"])
        if result.returncode != 0:
            console.print("[red]Failed to apply kustomizations[/red]")
            return False
        
        console.print("[green]Git-managed kustomizations applied[/green]")
        console.print("[blue]Infrastructure and applications will be deployed automatically from Git[/blue]")
        return True
    
    def _wait_for_gitops_deployment(self):
        """Wait for GitOps deployment completion"""
        console.print("\n[bold blue]Waiting for GitOps Deployment[/bold blue]\n")
        
        console.print("[blue]Monitoring infrastructure deployment...[/blue]")
        console.print("[cyan]This may take several minutes as Flux deploys:[/cyan]")
        console.print("  • NGINX Ingress Controller")
        console.print("  • Prometheus Monitoring Stack")
        console.print("  • Container Registry UI")
        console.print("  • Sample Applications\n")
        
        # Monitor kustomizations
        timeout = 900  # 15 minutes
        elapsed = 0
        interval = 10
        
        while elapsed < timeout:
            # Check infrastructure kustomization
            infra_result = self.tools.kubectl([
                "get", "kustomization", "dev-lab-infrastructure", "-n", "flux-system",
                "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}"
            ], capture_output=True)
            infra_ready = infra_result.stdout.strip() if infra_result.returncode == 0 else "Unknown"
            
            # Check apps kustomization
            apps_result = self.tools.kubectl([
                "get", "kustomization", "dev-lab-apps", "-n", "flux-system",
                "-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}"
            ], capture_output=True)
            apps_ready = apps_result.stdout.strip() if apps_result.returncode == 0 else "Unknown"
            
            # Display progress
            console.print(f"\r[blue]Infrastructure: {infra_ready}, Apps: {apps_ready} ({elapsed}s elapsed)[/blue]", end="")
            
            if infra_ready == "True" and apps_ready == "True":
                console.print("\n[green]GitOps deployment completed successfully![/green]")
                return
            
            time.sleep(interval)
            elapsed += interval
        
        console.print("\n[yellow] Deployment is taking longer than expected, but may still be in progress[/yellow]")
        console.print("[yellow]Use './devlab flux -- get kustomizations -A' to monitor status[/yellow]")
    
    def _show_gitops_info(self):
        """Show GitOps status and access information"""
        console.print("\n[bold green]Dev Lab GitOps deployment setup complete![/bold green]\n")
        
        # Show GitOps status
        console.print("[bold blue]GitOps Status:[/bold blue]")
        result = self.tools.flux(["get", "all", "-A"], capture_output=True)
        if result.returncode == 0:
            # Show first 20 lines
            lines = result.stdout.split('\n')[:20]
            for line in lines:
                if line.strip():
                    console.print(line)
        
        console.print("\n[bold blue]Access Information:[/bold blue]")
        table = Table(title="Service Access")
        table.add_column("Service", style="cyan")
        table.add_column("Command", style="green")
        
        table.add_row("Prometheus", "kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090")
        table.add_row("Grafana", "kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80")
        table.add_row("AlertManager", "kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093")
        table.add_row("Linkerd Viz", "linkerd viz dashboard")
        table.add_row("Registry UI", "kubectl port-forward -n dev-lab-registry svc/docker-registry-ui 5001:80")
        
        console.print(table)
        
        console.print("\n[bold blue]GitOps Monitoring Commands:[/bold blue]")
        console.print("• ./devlab flux -- get all -A                    # Overview of all Flux resources")
        console.print("• ./devlab flux -- logs --all-namespaces        # Controller logs")
        console.print("• watch ./devlab flux -- get kustomizations -A  # Watch reconciliation")
        console.print("• ./devlab kubectl -- get events -n flux-system # System events")
        
        console.print("\n[bold blue]Sample Application:[/bold blue]")
        console.print("• Add to /etc/hosts: 127.0.0.1 sample-app.local")
        console.print("• Access at: http://sample-app.local")
        
        console.print("\n[bold blue]Notes:[/bold blue]")
        console.print("• Infrastructure and apps are automatically deployed from Git")
        console.print("• Changes to dev-lab/ directory will be reconciled automatically")
        console.print("• Use Git commits to manage deployments")

ADDONS = {
    "keda": {
        "description": "KEDA event-driven pod autoscaling (ScaledObject/ScaledJob)",
        "release": ("keda", "keda"),
        "enable": "_enable_keda",
        "disable": "_disable_keda",
    },
    "node-autoscaler": {
        "description": "cluster-autoscaler with simulated KWOK nodes (node pool devlab.io/node-pool=kwok)",
        "release": ("cluster-autoscaler", "kube-system"),
        "enable": "_enable_node_autoscaler",
        "disable": "_disable_node_autoscaler",
    },
}


def show_access_points(monitoring: bool = True):
    """Print the ingress URLs of the bootstrap services."""
    table = Table(title="Access Points")
    table.add_column("Service", style="cyan")
    table.add_column("URL", style="green")
    table.add_column("Credentials", style="yellow")
    for service, url, credentials, needs_monitoring in ACCESS_POINTS:
        if monitoring or not needs_monitoring:
            table.add_row(service, url, credentials)
    console.print(table)


def parse_cobra_completions(output: str) -> List[CompletionItem]:
    """Convert Cobra's __complete output into Click completion items."""
    lines = output.splitlines()
    if lines and re.fullmatch(r":\d+", lines[-1]):
        lines.pop()

    items = []
    for line in lines:
        if not line or line.startswith("_activeHelp_"):
            continue
        value, separator, help_text = line.partition("\t")
        items.append(CompletionItem(value, help=help_text if separator else None))
    return items


def complete_tool(tool: str):
    """Create a Click completion callback for a wrapped CLI."""
    def shell_complete(ctx, param, incomplete):
        args = [*ctx.params.get(param.name, ()), incomplete]
        try:
            result = ContainerToolRunner().complete(tool, args)
        except (OSError, ValueError):
            return []
        if result.returncode != 0:
            return []
        return parse_cobra_completions(result.stdout)

    return shell_complete


@click.group()
@click.option("--profile", type=click.Choice(list(PROFILES)), default="local", show_default=True,
              envvar="DEVLAB_PROFILE", help="Defaults for local use or CI pipelines (env DEVLAB_PROFILE)")
def cli(profile):
    """Dev Lab - Platform-Agnostic Kubernetes Development Environment"""
    global ACTIVE_PROFILE
    ACTIVE_PROFILE = profile

@cli.command()
@click.option("--monitoring/--no-monitoring", default=None,
              help="Install the Prometheus/Grafana stack (default: yes locally, no in CI)")
@click.option("--krew/--no-krew", default=None,
              help="Install the default krew plugins (default: yes locally, no in CI)")
@click.option("--gpu", is_flag=True,
              help="GPU-enabled cluster: NVIDIA GPUs on the workers (cluster/gpu-workers.yaml) and the GPU Operator")
def bootstrap(monitoring, krew, gpu):
    """Bootstrap the dev-lab environment"""
    manager = DevLabManager()
    success = manager.bootstrap(monitoring=monitoring, krew=krew, gpu=gpu)
    sys.exit(0 if success else 1)

@cli.command(name='gpu-operator')
def gpu_operator():
    """Install or update the NVIDIA GPU Operator (applies time-slicing changes)"""
    manager = DevLabManager()
    sys.exit(0 if manager._setup_gpu_operator() else 1)

@cli.command(name='deploy-gitops')
def deploy_gitops():
    """Deploy using GitOps method with Flux CD"""
    manager = DevLabManager()
    success = manager.deploy_gitops()
    sys.exit(0 if success else 1)

PORT_SPEC = re.compile(r"^(\d*):(\d+)$|^(\d+)$")
# kubectl flags whose value is a separate argument, so it is not mistaken for
# the port-forward resource or a port
KUBECTL_VALUE_FLAGS = {
    "-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user",
    "-s", "--server", "--token", "--as", "--as-group", "--as-uid",
    "--request-timeout", "--pod-running-timeout", "-v", "--v",
}

def free_host_port() -> int:
    """Ask the OS for an unused TCP port on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

def docker_publish_address(address: str) -> str:
    address = "127.0.0.1" if address == "localhost" else address
    return f"[{address}]" if ":" in address else address

def prepare_port_forward(args: List[str]):
    """Make `kubectl port-forward` in the tool container reachable from the host.

    kubectl binds inside the container, so it listens on 0.0.0.0 there and
    each local port is published on the host with `docker run -p`. The host
    bind address comes from --address (default localhost, like kubectl). A
    port given as ":REMOTE" gets a free host port picked here, because a port
    kubectl picks inside the container cannot be published in advance.
    Returns (kubectl args, docker publish flags, [(local, remote)]).
    """
    if "port-forward" not in args:
        return list(args), [], []

    index = args.index("port-forward")
    head, tail = list(args[:index + 1]), list(args[index + 1:])
    addresses = ["127.0.0.1"]
    rewritten, publish, forwards = [], [], []
    resource_seen = False
    position = 0
    while position < len(tail):
        arg = tail[position]
        position += 1
        if arg == "--address" and position < len(tail):
            addresses = tail[position].split(",")
            position += 1
        elif arg.startswith("--address="):
            addresses = arg.split("=", 1)[1].split(",")
        elif arg.startswith("-"):
            rewritten.append(arg)
            if arg in KUBECTL_VALUE_FLAGS and position < len(tail):
                rewritten.append(tail[position])
                position += 1
        elif not resource_seen:
            resource_seen = True
            rewritten.append(arg)
        elif PORT_SPEC.match(arg):
            local, remote, single = PORT_SPEC.match(arg).groups()
            remote = remote or single
            local = local or (str(free_host_port()) if arg.startswith(":") else remote)
            rewritten.append(f"{local}:{remote}")
            forwards.append((local, remote))
            for address in addresses:
                publish.extend(["-p", f"{docker_publish_address(address)}:{local}:{local}"])
        else:
            rewritten.append(arg)

    return head + ["--address", "0.0.0.0"] + rewritten, publish, forwards

# Stop option parsing at the first positional argument so a literal "--" after
# it (e.g. "kubectl exec pod -- sh") reaches the wrapped tool. A leading "--"
# (e.g. "devlab kubectl -- get pods") is still consumed by Click.
PASSTHROUGH_SETTINGS = {
    "ignore_unknown_options": True,
    "allow_extra_args": True,
    "allow_interspersed_args": False,
    "help_option_names": [],
}

@cli.command(context_settings=PASSTHROUGH_SETTINGS)
@click.argument('args', nargs=-1, type=click.UNPROCESSED, shell_complete=complete_tool("kubectl"))
def kubectl(args):
    """Run kubectl commands"""
    manager = DevLabManager()
    if profile_setting("krew") and not (PROJECT_ROOT / ".krew" / "receipts").exists():
        manager.tools.ensure_krew_plugins()
    kubectl_args, publish, forwards = prepare_port_forward(list(args))
    for local, remote in forwards:
        console.print(f"[cyan]Host localhost:{local} -> {remote} (container listens on 0.0.0.0)[/cyan]")
    result = manager.tools.kubectl(kubectl_args, tty=interactive_terminal(), publish=publish)
    sys.exit(result.returncode)

@cli.command(name='krew-sync')
def krew_sync():
    """Install the default krew plugins into the containerized kubectl"""
    manager = DevLabManager()
    sys.exit(0 if manager.tools.ensure_krew_plugins() else 1)

@cli.command(context_settings=PASSTHROUGH_SETTINGS)
@click.argument('args', nargs=-1, type=click.UNPROCESSED, shell_complete=complete_tool("helm"))
def helm(args):
    """Run helm commands"""
    manager = DevLabManager()
    result = manager.tools.helm(list(args))
    sys.exit(result.returncode)

@cli.command(context_settings=PASSTHROUGH_SETTINGS)
@click.argument('args', nargs=-1, type=click.UNPROCESSED, shell_complete=complete_tool("linkerd"))
def linkerd(args):
    """Run linkerd commands"""
    manager = DevLabManager()
    result = manager.tools.linkerd(list(args), context=f"kind-{CLUSTER_NAME}")
    sys.exit(result.returncode)

@cli.command(context_settings=PASSTHROUGH_SETTINGS)
@click.argument('args', nargs=-1, type=click.UNPROCESSED, shell_complete=complete_tool("flux"))
def flux(args):
    """Run flux commands"""
    manager = DevLabManager()
    result = manager.tools.flux(list(args))
    sys.exit(result.returncode)

@cli.command(context_settings=PASSTHROUGH_SETTINGS)
@click.argument('args', nargs=-1, type=click.UNPROCESSED, shell_complete=complete_tool("kind"))
def kind(args):
    """Run kind commands"""
    manager = DevLabManager()
    result = manager.tools.kind(list(args))
    sys.exit(result.returncode)

def registry_image(image: str) -> str:
    """Qualify an image reference with the local registry host."""
    if image.startswith(f"{REGISTRY_HOST}/"):
        return image
    return f"{REGISTRY_HOST}/{image}"

def push_image(image: str) -> int:
    """Tag a local image for the dev-lab registry, if needed, and push it."""
    target = registry_image(image)
    source_exists = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True
    ).returncode == 0
    # "devlab push app:1" works for both a plain local "app:1" and one already
    # built as "localhost:5000/app:1" by "devlab build".
    if target != image and source_exists:
        result = subprocess.run(["docker", "tag", image, target])
        if result.returncode != 0:
            return result.returncode
    console.print(f"[blue]Pushing {target}[/blue]")
    result = subprocess.run(["docker", "push", target])
    if result.returncode == 0:
        console.print(f"[green]Pushed. Reference it in manifests as image: {target}[/green]")
    return result.returncode

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.option("-t", "--tag", "image", required=True, help="Image name[:tag]; localhost:5000/ is prepended if missing")
@click.option("--push", "push_after", is_flag=True, help="Push to the local registry after building")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def build(image, push_after, args):
    """Build an image for the local registry (extra args go to docker build)"""
    target = registry_image(image)
    build_args = list(args) or ["."]
    console.print(f"[blue]Building {target}[/blue]")
    result = subprocess.run(["docker", "build", "-t", target, *build_args])
    if result.returncode != 0 or not push_after:
        sys.exit(result.returncode)
    sys.exit(push_image(target))

@cli.command()
@click.argument("images", nargs=-1, required=True)
def push(images):
    """Push local images to the dev-lab registry at localhost:5000"""
    for image in images:
        returncode = push_image(image)
        if returncode != 0:
            sys.exit(returncode)

def kubectl_alias_completion(alias: str) -> str:
    """Bash completion for an alias of `devlab kubectl` (e.g. alias k='devlab kubectl')."""
    function = "_devlab_alias_" + re.sub(r"\W", "_", alias)
    return f"""
{function}() {{
    local COMP_WORDS=(devlab kubectl "${{COMP_WORDS[@]:1}}")
    local COMP_CWORD=$((COMP_CWORD + 1))
    _devlab_completion devlab
}}
complete -o nosort -F {function} {alias}
"""

@cli.command()
@click.argument("shell", type=click.Choice(["bash"]))
@click.option("--kubectl-alias", "kubectl_aliases", multiple=True, metavar="NAME",
              help="Also complete NAME as an alias for 'devlab kubectl' (repeatable)")
def completion(shell, kubectl_aliases):
    """Print a shell completion script"""
    completion_class = get_completion_class(shell)
    complete = completion_class(cli, {}, "devlab", "_DEVLAB_COMPLETE")
    click.echo(complete.source())
    for alias in kubectl_aliases:
        click.echo(kubectl_alias_completion(alias))

@cli.group()
def addon():
    """Enable or disable optional components (see AUTOSCALING.md)"""

@addon.command(name="list")
def addon_list():
    """List addons and whether they are installed"""
    manager = DevLabManager()
    table = Table(title="Addons")
    table.add_column("Addon", style="cyan")
    table.add_column("Installed")
    table.add_column("Description")
    for name, spec in ADDONS.items():
        installed = manager.addon_installed(name)
        table.add_row(name, "[green]yes[/green]" if installed else "no", spec["description"])
    console.print(table)

@addon.command(name="enable")
@click.argument("names", nargs=-1, required=True, type=click.Choice(list(ADDONS)))
def addon_enable(names):
    """Install addons (safe to re-run; upgrades in place)"""
    manager = DevLabManager()
    sys.exit(0 if all(manager.enable_addon(name) for name in names) else 1)

@addon.command(name="disable")
@click.argument("names", nargs=-1, required=True, type=click.Choice(list(ADDONS)))
def addon_disable(names):
    """Uninstall addons"""
    manager = DevLabManager()
    sys.exit(0 if all(manager.disable_addon(name) for name in names) else 1)

@cli.command()
def status():
    """Show cluster and service status"""
    manager = DevLabManager()
    
    console.print("[bold blue]Dev Lab Status[/bold blue]\n")
    
    # Check Docker
    if manager.check_docker():
        console.print("[green]Docker is running[/green]")
    else:
        console.print("[red]Docker is not available[/red]")
        return
    
    # Check cluster
    result = manager.tools.kubectl(["cluster-info"], capture_output=True)
    if result.returncode == 0:
        console.print("[green]Cluster is accessible[/green]")
    else:
        console.print("[red]Cluster is not accessible[/red]")
        return
    
    # Check nodes
    result = manager.tools.kubectl(["get", "nodes", "-o", "json"], capture_output=True)
    if result.returncode == 0:
        nodes = json.loads(result.stdout)
        table = Table(title="Cluster Nodes")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Role")
        table.add_column("GPUs")
        
        for node in nodes["items"]:
            name = node["metadata"]["name"]
            status = "Ready" if any(c["type"] == "Ready" and c["status"] == "True" 
                                  for c in node["status"]["conditions"]) else "NotReady"
            role = "control-plane" if "node-role.kubernetes.io/control-plane" in node["metadata"]["labels"] else "worker"
            
            gpus = node["status"].get("allocatable", {}).get("nvidia.com/gpu", "-")
            
            table.add_row(name, status, role, gpus)
        
        console.print(table)
        show_access_points(manager._has_service_monitor_crd())

@cli.command(name='build-tools')
def build_tools():
    """Build/rebuild local tool container images"""
    console.print("[bold blue]Building Local Tool Images[/bold blue]")
    
    manager = DevLabManager()
    
    # Build KinD image
    try:
        image_name = "devlab-kind:latest"
        console.print(f"[blue]Building {image_name}...[/blue]")
        manager.tools._build_kind_image(image_name)
        console.print("[green]KinD image built successfully[/green]")
    except Exception as e:
        console.print(f"[red]Failed to build KinD image: {e}[/red]")
        sys.exit(1)

    helm_image = manager.tools._ensure_helm_image()
    if helm_image is None:
        console.print("[red]Failed to build Helm image[/red]")
        sys.exit(1)
    console.print(f"[green]Helm image ready: {helm_image}[/green]")

    kubectl_image = manager.tools._ensure_kubectl_image()
    if kubectl_image is None:
        console.print("[red]Failed to build kubectl image[/red]")
        sys.exit(1)
    console.print(f"[green]kubectl image ready: {kubectl_image}[/green]")
    
    console.print("[green]All tool images built successfully![/green]")

@cli.command()
def cleanup():
    """Clean up the dev-lab environment"""
    manager = DevLabManager()
    
    if click.confirm("This will delete the entire dev-lab cluster. Continue?"):
        console.print("[blue]Cleaning up dev-lab environment...[/blue]")
        result = manager.tools.kind(["delete", "cluster", "--name", CLUSTER_NAME])
        if result.returncode == 0:
            console.print("[green]Cleanup completed[/green]")
        else:
            console.print("[red]Cleanup failed[/red]")

if __name__ == "__main__":
    try:
        cli.main(prog_name="devlab", standalone_mode=False)
    except (KeyboardInterrupt, click.Abort):
        console.print("\n[yellow]Interrupted. Exiting...[/yellow]")
        sys.exit(130)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except DevLabError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)