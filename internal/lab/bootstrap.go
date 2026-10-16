package lab

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"
)

// BootstrapOptions selects how bootstrap creates the cluster.
type BootstrapOptions struct {
	// GPU creates the cluster from the nvkind template and installs the
	// NVIDIA device plugin.
	GPU bool
	// Recreate deletes an existing dev-lab cluster without asking.
	Recreate bool
}

// Bootstrap creates the dev-lab cluster and installs Linkerd.
func (l *Lab) Bootstrap(ctx context.Context, opts BootstrapOptions) error {
	l.Log.Section("🚀 Bootstrapping Dev Lab Environment")

	if err := l.CheckDocker(ctx); err != nil {
		return err
	}
	if opts.GPU {
		if err := l.CheckGPUPrerequisites(ctx); err != nil {
			return err
		}
	}
	if err := l.createCluster(ctx, opts); err != nil {
		return err
	}
	if opts.GPU {
		if err := l.SetupGPUDevicePlugin(ctx); err != nil {
			return err
		}
	}
	if err := l.setupLinkerd(ctx); err != nil {
		return err
	}

	l.Log.Section("🎉 Bootstrap completed successfully!")
	l.showBootstrapInfo(opts.GPU)
	return nil
}

func (l *Lab) createCluster(ctx context.Context, opts BootstrapOptions) error {
	l.Log.Step("Creating KinD cluster...")

	exists, err := l.Cluster.Exists(ClusterName)
	if err != nil {
		return fmt.Errorf("listing kind clusters: %w", err)
	}
	if exists {
		l.Log.Warn("Cluster '%s' already exists", ClusterName)
		if !opts.Recreate && !l.confirm("Delete and recreate?") {
			if !l.clusterReachable(ctx) {
				return fmt.Errorf("existing cluster '%s' is not reachable; delete it with: devlab cleanup", ClusterName)
			}
			l.Log.Info("Using existing cluster")
			return nil
		}
		l.Log.Step("Deleting existing cluster...")
		if err := l.Cluster.Delete(ClusterName, l.Home.Kubeconfig()); err != nil {
			return fmt.Errorf("deleting cluster: %w", err)
		}
	}

	var config []byte
	var gpuNodes []gpuNode
	if opts.GPU {
		config, gpuNodes, err = l.renderGPUClusterConfig(ctx)
	} else {
		config, err = os.ReadFile(l.Home.Path("cluster", "kind-config.yaml"))
	}
	if err != nil {
		return err
	}

	if err := os.MkdirAll(l.RegistryDir, 0o755); err != nil {
		return fmt.Errorf("creating registry data directory: %w", err)
	}
	if err := os.MkdirAll(l.Home.Path(".kube"), 0o700); err != nil {
		return err
	}
	if err := l.Cluster.Create(ClusterName, config, l.Home.Kubeconfig(), 5*time.Minute); err != nil {
		return fmt.Errorf("creating cluster: %w", err)
	}

	if opts.GPU {
		if err := l.setupGPUNodes(ctx, gpuNodes); err != nil {
			return err
		}
	}

	l.Log.Step("Waiting for nodes to be ready...")
	if err := l.kubectl(ctx, "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=300s"); err != nil {
		return fmt.Errorf("waiting for nodes: %w", err)
	}
	l.Log.OK("Cluster created successfully (kubeconfig: %s)", l.Home.Kubeconfig())
	return nil
}

func (l *Lab) setupLinkerd(ctx context.Context) error {
	l.Log.Step("Setting up Linkerd service mesh...")

	l.Log.Step("Installing Gateway API CRDs...")
	if err := l.applyFile(ctx, GatewayAPIURL); err != nil {
		return fmt.Errorf("installing Gateway API CRDs: %w", err)
	}
	if err := l.kubectl(ctx, "wait", "--for", "condition=established", "--timeout=60s",
		"crd/gateways.gateway.networking.k8s.io", "crd/httproutes.gateway.networking.k8s.io"); err != nil {
		return fmt.Errorf("waiting for Gateway API CRDs: %w", err)
	}

	if err := l.Run.Run(ctx, l.ToolCmd("linkerd", "check", "--pre", "--context", Context)); err != nil {
		return fmt.Errorf("linkerd pre-flight checks failed: %w", err)
	}

	l.Log.Step("Installing Linkerd CRDs...")
	if err := l.linkerdApply(ctx, "install", "--crds"); err != nil {
		return err
	}
	l.Log.Step("Installing Linkerd control plane...")
	if err := l.linkerdApply(ctx, "install"); err != nil {
		return err
	}
	if err := l.kubectl(ctx, "wait", "--for=condition=available", "deployment",
		"-n", "linkerd", "--all", "--timeout=300s"); err != nil {
		return fmt.Errorf("waiting for Linkerd: %w", err)
	}

	l.Log.Step("Installing Linkerd Viz...")
	if err := l.linkerdApply(ctx, "viz", "install"); err != nil {
		return err
	}
	if err := l.kubectl(ctx, "wait", "--for=condition=available", "deployment",
		"-n", "linkerd-viz", "--all", "--timeout=300s"); err != nil {
		return fmt.Errorf("waiting for Linkerd Viz: %w", err)
	}

	l.Log.OK("Linkerd setup completed")
	return nil
}

// linkerdApply renders manifests with the linkerd CLI and applies them.
func (l *Lab) linkerdApply(ctx context.Context, args ...string) error {
	manifest, err := l.Run.Output(ctx, l.ToolCmd("linkerd", append(args, "--context", Context)...))
	if err != nil {
		return fmt.Errorf("linkerd %s: %w", strings.Join(args, " "), err)
	}
	if err := l.applyManifest(ctx, manifest); err != nil {
		return fmt.Errorf("applying linkerd %s: %w", strings.Join(args, " "), err)
	}
	return nil
}

func (l *Lab) showBootstrapInfo(gpu bool) {
	log := l.Log
	log.Info("🎯 What's Next?")
	log.Plain("\nAvailable Commands:")
	log.Plain("  • bin/devlab kubectl get nodes   - Check cluster status")
	log.Plain("  • bin/devlab linkerd check       - Verify Linkerd installation")
	log.Plain("  • bin/devlab helm list -A        - List installed Helm charts")
	log.Plain("  • bin/devlab status              - Show environment status")
	if gpu {
		log.Plain("  • bin/devlab kubectl apply -f config/gpu/gpu-test-pod.yaml - Run a GPU smoke test")
		log.Plain("  • bin/devlab kubectl logs gpu-test                         - Show GPUs seen by the smoke test")
		log.Plain("\nGPU Workloads:")
		log.Plain("  • Request nvidia.com/gpu in resource limits and set runtimeClassName: nvidia")
		log.Plain("  • Change GPU placement in cluster/nvkind-values.yaml, then re-run bootstrap --gpu")
		log.Plain("  • Each GPU is time-sliced into shares; change this in config/gpu/nvidia-device-plugin-values.yaml, then run bin/devlab gpu-plugin")
		log.Plain("  • Dask GPU workers: see DASK-GPU-RUNBOOK.md")
	}
	log.Plain("\nAccess Points:")
	log.Plain("  • Linkerd Viz: bin/devlab linkerd viz dashboard")
	log.Plain("  • Kubeconfig: export KUBECONFIG=%s", l.Home.Kubeconfig())
	log.Plain("\nNext Steps:")
	log.Plain("  1. Deploy with bin/devlab deploy-traditional (registry, metrics-server, ingress, monitoring)")
	log.Plain("  2. Or set up GitOps with bin/devlab deploy-gitops (Flux manages the infrastructure)")
	log.Plain("  3. Check everything with bin/devlab status")
}
