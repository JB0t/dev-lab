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
from typing import Dict, List, Optional
import argparse
import time

# Third-party imports (will be in requirements.txt)
import click
import docker
import yaml
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

# Container tool versions
TOOL_VERSIONS = {
    "kubectl": "v1.28.3",
    "helm": "v3.13.1",
    "linkerd": "stable-2.14.5",
    "kind": "v0.20.0",
    "flux": "v2.1.2"
}

class DevLabError(Exception):
    """Custom exception for dev-lab operations"""
    pass

class ContainerToolRunner:
    """Runs Kubernetes tools in containers for platform independence"""
    
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
    
    def kubectl(self, args: List[str], capture_output: bool = False, context: str = None, input: str = None, text: bool = False) -> subprocess.CompletedProcess:
        """Run kubectl in container"""
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "kind",  # Use kind network to communicate with KinD cluster
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",  # Use shared kubeconfig
            "-v", f"{PROJECT_ROOT}:/workspace:rw",
            "-w", "/workspace",
            "alpine/kubectl:latest",
        ]
        
        # Add context if specified
        if context:
            cmd.extend(["--context", context])
        
        cmd.extend(args)
        
        return subprocess.run(cmd, capture_output=capture_output, text=text, input=input)
    
    def helm(self, args: List[str], capture_output: bool = False, input: str = None, text: bool = False) -> subprocess.CompletedProcess:
        """Run helm in container"""
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "kind",  # Use kind network to communicate with KinD cluster
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",  # Use shared kubeconfig
            "-v", f"{PROJECT_ROOT}:/workspace:rw",
            "-w", "/workspace",
            "alpine/helm:latest",
        ] + args
        
        return subprocess.run(cmd, capture_output=capture_output, text=text, input=input)
    
    def kind(self, args: List[str], capture_output: bool = False) -> subprocess.CompletedProcess:
        """Run kind CLI - try host first, then local container image as fallback"""
        # First try to use host kind binary for better performance
        try:
            result = subprocess.run(["which", "kind"], capture_output=True, text=True)
            if result.returncode == 0:
                # Host kind is available, but we need to ensure it uses our shared kubeconfig
                env = os.environ.copy()
                env["KUBECONFIG"] = str(self.shared_kubeconfig_path)
                cmd = ["kind"] + args
                return subprocess.run(cmd, capture_output=capture_output, text=True, env=env)
        except FileNotFoundError:
            pass
        
        # Fallback: use local kind container image
        image_name = "devlab-kind:latest"
        
        # Check if our local kind image exists, build if not
        try:
            result = subprocess.run(["docker", "image", "inspect", image_name], 
                                   capture_output=True, text=True)
            if result.returncode != 0:
                console.print("[blue]Building local KinD container image (one-time setup)...[/blue]")
                self._build_kind_image(image_name)
        except Exception as e:
            console.print(f"[red]Error checking/building KinD image: {e}[/red]")
            return subprocess.CompletedProcess([], 1, "", str(e))
        
        console.print("[yellow]KinD not found on host, using local container image...[/yellow]")
        
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "host",
            "-v", "/var/run/docker.sock:/var/run/docker.sock:rw",
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",
            "-v", f"{PROJECT_ROOT}:/workspace:rw",
            "-w", "/workspace",
            image_name
        ] + args
        
        return subprocess.run(cmd, capture_output=capture_output, text=True)
    
    def _build_kind_image(self, image_name: str):
        """Build the local KinD container image"""
        dockerfile_path = Path(__file__).parent / "Dockerfile.kind"
        
        if not dockerfile_path.exists():
            raise FileNotFoundError(f"Dockerfile.kind not found at {dockerfile_path}")
        
        build_cmd = [
            "docker", "build", 
            "-f", str(dockerfile_path),
            "-t", image_name,
            str(dockerfile_path.parent)
        ]
        
        console.print(f"[blue]Building {image_name} from {dockerfile_path}...[/blue]")
        result = subprocess.run(build_cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            console.print(f"[red]Failed to build KinD image:[/red]")
            console.print(result.stderr)
            raise RuntimeError(f"Failed to build {image_name}")
        
        console.print(f"[green]✅ Successfully built {image_name}[/green]")
    
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
    
    def _run_container(self, image: str, args: List[str], capture_output: bool = False, text: bool = False, input: str = None, context: str = None) -> subprocess.CompletedProcess:
        """Run a tool in a container with shared kubeconfig and kind network"""
        cmd = [
            "docker", "run", "--rm", "-i",
            "--network", "kind",  # Use kind network to communicate with KinD cluster
            "-v", f"{self.shared_kubeconfig_dir}:/root/.kube:rw",  # Use shared kubeconfig
            "-v", f"{PROJECT_ROOT}:/workspace:rw",
            "-w", "/workspace",
        ]
        
        # Add user mapping for flux to read kubeconfig (flux runs as nobody:65534)
        if "flux" in image:
            cmd.extend(["-u", "root"])  # Run as root to access mounted kubeconfig
        
        cmd.append(image)
        
        # Add kubeconfig and context flags for linkerd and flux
        if "linkerd" in image or "flux" in image:
            cmd.extend(["--kubeconfig", "/root/.kube/config"])
            if context:
                cmd.extend(["--context", context])
            elif "flux" in image:
                cmd.extend(["--context", f"kind-{CLUSTER_NAME}"])
        
        cmd.extend(args)
        
        return subprocess.run(cmd, capture_output=capture_output, text=text, input=input)
    
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
    
    def bootstrap(self) -> bool:
        """Bootstrap the complete dev-lab environment"""
        console.print("[bold blue]🚀 Bootstrapping Dev Lab Environment[/bold blue]")
        
        if not self.check_docker():
            return False
        
        # Ensure shared kubeconfig is available
        self.tools._ensure_shared_kubeconfig()
        
        # Create cluster
        if not self._create_cluster():
            return False
        
        # Setup Linkerd
        if not self._setup_linkerd():
            return False
        
        console.print("\n[bold green]🎉 Bootstrap completed successfully![/bold green]")
        self._show_bootstrap_info()
        return True
    
    def _show_bootstrap_info(self) -> None:
        """Display helpful information after bootstrap"""
        console.print("\n[bold cyan]🎯 What's Next?[/bold cyan]")
        console.print("\n[green]Available Commands:[/green]")
        console.print("  • [cyan]./devlab kubectl get nodes[/cyan] - Check cluster status")
        console.print("  • [cyan]./devlab linkerd check[/cyan] - Verify Linkerd installation")
        console.print("  • [cyan]./devlab helm list[/cyan] - List installed Helm charts")
        console.print("  • [cyan]./devlab status[/cyan] - Show environment status")
        console.print("\n[green]Access Points:[/green]")
        console.print(f"  • [cyan]Linkerd Viz:[/cyan] http://localhost:50750 (after: ./devlab linkerd viz dashboard)")
        console.print("\n[yellow]Next Steps:[/yellow]")
        console.print("  1. Deploy applications with [cyan]./devlab deploy-traditional[/cyan] (includes registry, metrics-server, ingress, monitoring)")
        console.print("  2. Or setup GitOps with [cyan]./devlab deploy-gitops[/cyan] (Flux manages all infrastructure including metrics-server)")
        console.print("  3. Check everything with [cyan]./devlab status[/cyan]")
    
    def _create_cluster(self) -> bool:
        """Create KinD cluster"""
        console.print("[blue]Creating KinD cluster...[/blue]")
        
        # Check if cluster already exists
        result = self.tools.kind(["get", "clusters"], capture_output=True)
        if CLUSTER_NAME in result.stdout:
            console.print(f"[yellow]Cluster '{CLUSTER_NAME}' already exists[/yellow]")
            if not click.confirm("Delete and recreate?"):
                return True
            
            console.print("[blue]Deleting existing cluster...[/blue]")
            self.tools.kind(["delete", "cluster", "--name", CLUSTER_NAME])
        
        # Create cluster with config
        config_file = PROJECT_ROOT / "cluster" / "kind-config.yaml"
        if not config_file.exists():
            console.print(f"[red]Kind config not found at {config_file}[/red]")
            return False
        
        result = self.tools.kind([
            "create", "cluster", 
            "--config", config_file,
            "--wait", "300s"
        ])
        
        if result.returncode != 0:
            console.print("[red]Failed to create cluster[/red]")
            return False
        
        # Fix kubeconfig to use the container network IP
        if not self._fix_kubeconfig_for_containers():
            return False
        
        # Wait for nodes to be ready
        console.print("[blue]Waiting for nodes to be ready...[/blue]")
        self.tools.kubectl(["wait", "--for=condition=Ready", "nodes", "--all", "--timeout=300s"], context="kind-dev-lab")
        
        console.print("[green]✅ Cluster created successfully[/green]")
        return True
    
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
            
            console.print("[green]✅ Kubeconfig updated for container networking[/green]")
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
        
        console.print("[green]✅ Linkerd setup completed[/green]")
        return True
    
    def _setup_registry(self) -> bool:
        """Setup local container registry"""
        console.print("[blue]Setting up local container registry...[/blue]")
        
        # Create namespace
        console.print("[blue]Creating registry namespace...[/blue]")
        self.tools.kubectl([
            "create", "namespace", "dev-lab-registry"
        ], context=f"kind-{CLUSTER_NAME}")
        
        # Apply registry configuration
        registry_config = CONFIG_DIR / "registry" / "registry-daemonset.yaml"
        if not registry_config.exists():
            console.print(f"[red]Registry config not found at {registry_config}[/red]")
            return False
        
        self.tools.kubectl(["apply", "-f", f"/workspace/config/registry/registry-daemonset.yaml"], context=f"kind-{CLUSTER_NAME}")
        
        # Apply registry UI
        registry_ui_config = CONFIG_DIR / "registry" / "registry-ui.yaml"
        if registry_ui_config.exists():
            self.tools.kubectl(["apply", "-f", f"/workspace/config/registry/registry-ui.yaml"], context=f"kind-{CLUSTER_NAME}")
        
        # Wait for registry to be ready
        self.tools.kubectl([
            "wait", "--for=condition=ready", "pod", 
            "-l", "app=docker-registry", "-n", "dev-lab-registry", "--timeout=300s"
        ], context=f"kind-{CLUSTER_NAME}")
        
        console.print("[green]✅ Registry setup completed[/green]")
        return True
    
    def _setup_metrics_server(self) -> bool:
        """Setup metrics server"""
        console.print("[blue]Setting up metrics server...[/blue]")
        
        # Install metrics server
        self.tools.kubectl([
            "apply", "-f", 
            "https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml"
        ], context=f"kind-{CLUSTER_NAME}")
        
        # Patch for KinD
        patch = '[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
        self.tools.kubectl([
            "patch", "deployment", "metrics-server", "-n", "kube-system",
            "--type=json", f"--patch={patch}"
        ], context=f"kind-{CLUSTER_NAME}")
        
        # Wait for metrics server
        self.tools.kubectl([
            "wait", "--for=condition=available", "deployment/metrics-server",
            "-n", "kube-system", "--timeout=300s"
        ], context=f"kind-{CLUSTER_NAME}")
        
        console.print("[green]✅ Metrics server setup completed[/green]")
        return True
    
    def deploy_traditional(self) -> bool:
        """Deploy using traditional script-based method"""
        console.print("[bold blue]🚀 Traditional Deployment[/bold blue]")
        
        if not self._check_bootstrap():
            return False
        
        # Setup container registry (not included in bootstrap for GitOps compatibility)
        if not self._setup_registry():
            return False
        
        # Setup metrics server (not included in bootstrap for GitOps compatibility)
        if not self._setup_metrics_server():
            return False
        
        # Install NGINX Ingress
        if not self._install_nginx_ingress():
            return False
        
        # Deploy monitoring
        if not self._deploy_monitoring():
            return False
        
        # Deploy sample apps
        if not self._deploy_sample_apps():
            return False
        
        self._show_access_info()
        return True
    
    def _check_bootstrap(self) -> bool:
        """Check if bootstrap was completed"""
        console.print("[blue]Checking bootstrap prerequisites...[/blue]")
        
        # Check cluster
        result = self.tools.kubectl(["cluster-info", "--context", f"kind-{CLUSTER_NAME}"], capture_output=True)
        if result.returncode != 0:
            console.print("[red]dev-lab cluster not found or not accessible[/red]")
            return False
        
        # Check Linkerd
        result = self.tools.kubectl(["get", "ns", "linkerd"], capture_output=True)
        if result.returncode != 0:
            console.print("[red]Linkerd not found[/red]")
            return False
        
        # Check registry
        result = self.tools.kubectl([
            "get", "pods", "-n", "dev-lab-registry", 
            "-l", "app=docker-registry", "--field-selector=status.phase=Running"
        ], capture_output=True)
        if result.returncode != 0:
            console.print("[red]Local registry not running[/red]")
            return False
        
        console.print("[green]✅ Bootstrap prerequisites verified[/green]")
        return True
    
    def _install_nginx_ingress(self) -> bool:
        """Install NGINX Ingress Controller"""
        console.print("[blue]Installing NGINX Ingress Controller...[/blue]")
        
        # Check if already installed
        result = self.tools.kubectl(["get", "ns", "ingress-nginx"], capture_output=True)
        if result.returncode == 0:
            console.print("[yellow]NGINX Ingress already installed[/yellow]")
            return True
        
        # Install NGINX Ingress for KinD
        self.tools.kubectl([
            "apply", "-f",
            "https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/kind/deploy.yaml"
        ])
        
        # Wait for ingress controller
        self.tools.kubectl([
            "wait", "--namespace", "ingress-nginx",
            "--for=condition=ready", "pod",
            "--selector=app.kubernetes.io/component=controller",
            "--timeout=300s"
        ])
        
        console.print("[green]✅ NGINX Ingress Controller installed[/green]")
        return True
    
    def _deploy_monitoring(self) -> bool:
        """Deploy monitoring stack"""
        console.print("[blue]Deploying monitoring stack...[/blue]")
        
        # Check if already installed
        result = self.tools.kubectl([
            "get", "deployment", "-n", "monitoring", 
            "kube-prometheus-stack-operator"
        ], capture_output=True)
        if result.returncode == 0:
            console.print("[yellow]Monitoring stack already installed[/yellow]")
            return True
        
        # Add Helm repositories
        self.tools.helm(["repo", "add", "prometheus-community", "https://prometheus-community.github.io/helm-charts"])
        self.tools.helm(["repo", "add", "grafana", "https://grafana.github.io/helm-charts"])
        self.tools.helm(["repo", "update"])
        
        # Create monitoring namespace
        self.tools.kubectl([
            "create", "namespace", "monitoring", 
            "--dry-run=client", "-o", "yaml"
        ])
        self.tools.kubectl(["apply", "-f", "-"])
        
        # Install Prometheus stack
        values_file = CONFIG_DIR / "monitoring" / "prometheus-values.yaml"
        if not values_file.exists():
            console.print(f"[red]Prometheus values not found at {values_file}[/red]")
            return False
        
        self.tools.helm([
            "upgrade", "--install", "kube-prometheus-stack",
            "prometheus-community/kube-prometheus-stack",
            "--namespace", "monitoring",
            "--values", "/workspace/config/monitoring/prometheus-values.yaml"
        ])
        
        # Wait for monitoring stack
        self.tools.kubectl([
            "wait", "--for=condition=ready", "pod",
            "-l", "app.kubernetes.io/name=kube-prometheus-stack",
            "-n", "monitoring", "--timeout=300s"
        ])
        
        console.print("[green]✅ Monitoring stack deployed[/green]")
        return True
    
    def _deploy_sample_apps(self) -> bool:
        """Deploy sample applications"""
        console.print("[blue]Deploying sample applications...[/blue]")
        
        # Create namespace
        self.tools.kubectl([
            "create", "namespace", "mesh-test",
            "--dry-run=client", "-o", "yaml"
        ])
        self.tools.kubectl(["apply", "-f", "-"])
        
        # Annotate for Linkerd injection
        self.tools.kubectl([
            "annotate", "namespace", "mesh-test",
            "linkerd.io/inject=enabled", "--overwrite"
        ])
        
        # Apply sample app
        app_config = CONFIG_DIR / "apps" / "sample-web-app.yaml"
        if not app_config.exists():
            console.print(f"[red]Sample app config not found at {app_config}[/red]")
            return False
        
        self.tools.kubectl(["apply", "-f", "/workspace/config/apps/sample-web-app.yaml"])
        
        # Wait for deployment
        self.tools.kubectl([
            "wait", "--for=condition=available", "deployment/sample-web-app",
            "-n", "mesh-test", "--timeout=300s"
        ])
        
        console.print("[green]✅ Sample applications deployed[/green]")
        return True
    
    def _show_access_info(self):
        """Show access information"""
        console.print("\n[bold green]🎉 Dev Lab deployment completed![/bold green]\n")
        
        table = Table(title="Access Information")
        table.add_column("Service", style="cyan")
        table.add_column("URL", style="green")
        table.add_column("Credentials", style="yellow")
        
        table.add_row("Prometheus", "http://localhost:30090", "-")
        table.add_row("Grafana", "http://localhost:30030", "admin/admin123")
        table.add_row("AlertManager", "http://localhost:9093", "-")
        table.add_row("Registry", "http://localhost:5000", "-")
        table.add_row("Sample App", "http://sample-app.local", "Add to /etc/hosts")
        
        console.print(table)
        
        console.print("\n[bold blue]Useful Commands:[/bold blue]")
        console.print("• python devlab.py status           # Check status")
        console.print("• python devlab.py kubectl -- get pods -A")
        console.print("• python devlab.py linkerd -- check")
    
    def deploy_gitops(self) -> bool:
        """Deploy using GitOps method with Flux CD"""
        console.print("[bold blue]🚀 GitOps Deployment[/bold blue]")
        
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
                console.print("[green]✅ Flux controllers already installed[/green]")
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
        
        console.print("[green]✅ Flux controllers installed and ready[/green]")
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
        
        console.print("[green]✅ SSH key pair generated[/green]")
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
        
        console.print("[green]✅ dev-lab-repo secret created[/green]")
        return True
    
    def _show_deploy_key(self):
        """Display deploy key for GitHub setup"""
        console.print("\n[bold blue]📋 GitHub Deploy Key Setup[/bold blue]\n")
        
        console.print("[cyan]Add this public key as a deploy key to your GitHub repository:[/cyan]")
        console.print(f"[cyan]Repository:[/cyan] https://github.com/jbotstevens/notes")
        console.print(f"[cyan]Settings → Deploy keys → Add deploy key[/cyan]\n")
        
        console.print("[yellow]Public Key:[/yellow]")
        console.print("─" * 50)
        with open(f"{KEY_PATH}.pub", "r") as f:
            console.print(f.read().strip())
        console.print("─" * 50)
        
        console.print("\n[yellow]⚠️  Make sure to:[/yellow]")
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
            console.print("[green]✅ GitRepository synced successfully[/green]")
        else:
            console.print("[yellow]⚠️  GitRepository may not be ready yet. Continuing...[/yellow]")
        
        return True
    
    def _apply_git_kustomizations(self) -> bool:
        """Apply Git-managed kustomizations"""
        console.print("[blue]Applying Git-managed kustomizations...[/blue]")
        
        # Apply the cluster-specific kustomizations
        kustomizations_file = PROJECT_ROOT / "clusters" / "dev-lab" / "dev-lab-kustomizations.yaml"
        if not kustomizations_file.exists():
            console.print(f"[yellow]⚠️  Kustomizations file not found at {kustomizations_file}[/yellow]")
            console.print("[yellow]GitOps setup complete, but manual kustomizations not applied[/yellow]")
            return True
        
        result = self.tools.kubectl(["apply", "-f", "/workspace/clusters/dev-lab/dev-lab-kustomizations.yaml"])
        if result.returncode != 0:
            console.print("[red]Failed to apply kustomizations[/red]")
            return False
        
        console.print("[green]✅ Git-managed kustomizations applied[/green]")
        console.print("[blue]Infrastructure and applications will be deployed automatically from Git[/blue]")
        return True
    
    def _wait_for_gitops_deployment(self):
        """Wait for GitOps deployment completion"""
        console.print("\n[bold blue]🕐 Waiting for GitOps Deployment[/bold blue]\n")
        
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
                console.print("\n[green]✅ GitOps deployment completed successfully![/green]")
                return
            
            time.sleep(interval)
            elapsed += interval
        
        console.print("\n[yellow]⚠️  Deployment is taking longer than expected, but may still be in progress[/yellow]")
        console.print("[yellow]Use './devlab flux -- get kustomizations -A' to monitor status[/yellow]")
    
    def _show_gitops_info(self):
        """Show GitOps status and access information"""
        console.print("\n[bold green]🎉 Dev Lab GitOps deployment setup complete![/bold green]\n")
        
        # Show GitOps status
        console.print("[bold blue]🔄 GitOps Status:[/bold blue]")
        result = self.tools.flux(["get", "all", "-A"], capture_output=True)
        if result.returncode == 0:
            # Show first 20 lines
            lines = result.stdout.split('\n')[:20]
            for line in lines:
                if line.strip():
                    console.print(line)
        
        console.print("\n[bold blue]📊 Access Information:[/bold blue]")
        table = Table(title="Service Access")
        table.add_column("Service", style="cyan")
        table.add_column("Command", style="green")
        
        table.add_row("Prometheus", "kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090")
        table.add_row("Grafana", "kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80")
        table.add_row("AlertManager", "kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093")
        table.add_row("Linkerd Viz", "linkerd viz dashboard")
        table.add_row("Registry UI", "kubectl port-forward -n dev-lab-registry svc/docker-registry-ui 5001:80")
        
        console.print(table)
        
        console.print("\n[bold blue]🔧 GitOps Monitoring Commands:[/bold blue]")
        console.print("• ./devlab flux -- get all -A                    # Overview of all Flux resources")
        console.print("• ./devlab flux -- logs --all-namespaces        # Controller logs")
        console.print("• watch ./devlab flux -- get kustomizations -A  # Watch reconciliation")
        console.print("• ./devlab kubectl -- get events -n flux-system # System events")
        
        console.print("\n[bold blue]🚀 Sample Application:[/bold blue]")
        console.print("• Add to /etc/hosts: 127.0.0.1 sample-app.local")
        console.print("• Access at: http://sample-app.local")
        
        console.print("\n[bold blue]📝 Notes:[/bold blue]")
        console.print("• Infrastructure and apps are automatically deployed from Git")
        console.print("• Changes to dev-lab/ directory will be reconciled automatically")
        console.print("• Use Git commits to manage deployments")

@click.group()
def cli():
    """Dev Lab - Platform-Agnostic Kubernetes Development Environment"""
    pass

@cli.command()
def bootstrap():
    """Bootstrap the dev-lab environment"""
    manager = DevLabManager()
    success = manager.bootstrap()
    sys.exit(0 if success else 1)

@cli.command(name='deploy-traditional')
def deploy_traditional():
    """Deploy using traditional method"""
    manager = DevLabManager()
    success = manager.deploy_traditional()
    sys.exit(0 if success else 1)

@cli.command(name='deploy-gitops')
def deploy_gitops():
    """Deploy using GitOps method with Flux CD"""
    manager = DevLabManager()
    success = manager.deploy_gitops()
    sys.exit(0 if success else 1)

@cli.command()
def deploy():
    """Deploy using traditional method (default)"""
    manager = DevLabManager()
    success = manager.deploy_traditional()
    sys.exit(0 if success else 1)

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def kubectl(args):
    """Run kubectl commands"""
    manager = DevLabManager()
    result = manager.tools.kubectl(list(args))
    sys.exit(result.returncode)

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def helm(args):
    """Run helm commands"""
    manager = DevLabManager()
    result = manager.tools.helm(list(args))
    sys.exit(result.returncode)

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def linkerd(args):
    """Run linkerd commands"""
    manager = DevLabManager()
    result = manager.tools.linkerd(list(args), context=f"kind-{CLUSTER_NAME}")
    sys.exit(result.returncode)

@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def flux(args):
    """Run flux commands"""
    manager = DevLabManager()
    result = manager.tools.flux(list(args))
    sys.exit(result.returncode)

@cli.command()
def status():
    """Show cluster and service status"""
    manager = DevLabManager()
    
    console.print("[bold blue]Dev Lab Status[/bold blue]\n")
    
    # Check Docker
    if manager.check_docker():
        console.print("[green]✅ Docker is running[/green]")
    else:
        console.print("[red]❌ Docker is not available[/red]")
        return
    
    # Check cluster
    result = manager.tools.kubectl(["cluster-info"], capture_output=True)
    if result.returncode == 0:
        console.print("[green]✅ Cluster is accessible[/green]")
    else:
        console.print("[red]❌ Cluster is not accessible[/red]")
        return
    
    # Check nodes
    result = manager.tools.kubectl(["get", "nodes", "-o", "json"], capture_output=True)
    if result.returncode == 0:
        nodes = json.loads(result.stdout)
        table = Table(title="Cluster Nodes")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Role")
        
        for node in nodes["items"]:
            name = node["metadata"]["name"]
            status = "Ready" if any(c["type"] == "Ready" and c["status"] == "True" 
                                  for c in node["status"]["conditions"]) else "NotReady"
            role = "control-plane" if "node-role.kubernetes.io/control-plane" in node["metadata"]["labels"] else "worker"
            
            table.add_row(name, status, role)
        
        console.print(table)

@cli.command(name='build-tools')
def build_tools():
    """Build/rebuild local tool container images"""
    console.print("[bold blue]🔨 Building Local Tool Images[/bold blue]")
    
    manager = DevLabManager()
    
    # Build KinD image
    try:
        image_name = "devlab-kind:latest"
        console.print(f"[blue]Building {image_name}...[/blue]")
        manager.tools._build_kind_image(image_name)
        console.print("[green]✅ KinD image built successfully[/green]")
    except Exception as e:
        console.print(f"[red]❌ Failed to build KinD image: {e}[/red]")
        sys.exit(1)
    
    console.print("[green]🎉 All tool images built successfully![/green]")

@cli.command()
def cleanup():
    """Clean up the dev-lab environment"""
    manager = DevLabManager()
    
    if click.confirm("This will delete the entire dev-lab cluster. Continue?"):
        console.print("[blue]Cleaning up dev-lab environment...[/blue]")
        result = manager.tools.kind(["delete", "cluster", "--name", CLUSTER_NAME])
        if result.returncode == 0:
            console.print("[green]✅ Cleanup completed[/green]")
        else:
            console.print("[red]❌ Cleanup failed[/red]")

if __name__ == "__main__":
    cli()