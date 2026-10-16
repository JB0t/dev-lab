package lab

import (
	"context"
	"fmt"
	"strings"
)

// DeployTraditional installs the registry, metrics-server, NGINX ingress and
// the monitoring stack directly (no GitOps).
func (l *Lab) DeployTraditional(ctx context.Context) error {
	l.Log.Section("🚀 Traditional Deployment")

	if err := l.checkBootstrap(ctx); err != nil {
		return err
	}
	steps := []func(context.Context) error{
		l.setupRegistry,
		l.setupMetricsServer,
		l.installNginxIngress,
		l.deployMonitoring,
	}
	for _, step := range steps {
		if err := step(ctx); err != nil {
			return err
		}
	}
	l.showAccessInfo()
	return nil
}

// checkBootstrap fails unless bootstrap has run: cluster reachable and
// Linkerd installed.
func (l *Lab) checkBootstrap(ctx context.Context) error {
	l.Log.Step("Checking bootstrap prerequisites...")
	if !l.clusterReachable(ctx) {
		return fmt.Errorf("dev-lab cluster not found or not accessible: run bin/devlab bootstrap first")
	}
	if _, err := l.kubectlOutput(ctx, "get", "namespace", "linkerd"); err != nil {
		return fmt.Errorf("Linkerd not found: run bin/devlab bootstrap first")
	}
	l.Log.OK("Bootstrap prerequisites verified")
	return nil
}

// ensureNamespace creates a namespace if it does not exist.
func (l *Lab) ensureNamespace(ctx context.Context, name string) error {
	return l.applyManifest(ctx, fmt.Sprintf("apiVersion: v1\nkind: Namespace\nmetadata:\n  name: %s\n", name))
}

func (l *Lab) setupRegistry(ctx context.Context) error {
	l.Log.Step("Setting up local container registry...")
	if err := l.ensureNamespace(ctx, "dev-lab-registry"); err != nil {
		return fmt.Errorf("creating registry namespace: %w", err)
	}
	for _, file := range []string{"registry-daemonset.yaml", "registry-ui.yaml"} {
		if err := l.applyFile(ctx, l.Home.Path("config", "registry", file)); err != nil {
			return fmt.Errorf("applying %s: %w", file, err)
		}
	}
	if err := l.kubectl(ctx, "rollout", "status", "daemonset/docker-registry",
		"-n", "dev-lab-registry", "--timeout=300s"); err != nil {
		return fmt.Errorf("waiting for registry: %w", err)
	}
	l.Log.OK("Registry setup completed")
	return nil
}

func (l *Lab) setupMetricsServer(ctx context.Context) error {
	l.Log.Step("Setting up metrics server...")
	if err := l.applyFile(ctx, MetricsServerURL); err != nil {
		return fmt.Errorf("installing metrics-server: %w", err)
	}
	// kind kubelets use self-signed serving certificates
	const patch = `[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]`
	args, err := l.kubectlOutput(ctx, "get", "deployment", "metrics-server", "-n", "kube-system",
		"-o", "jsonpath={.spec.template.spec.containers[0].args}")
	if err != nil {
		return fmt.Errorf("reading metrics-server args: %w", err)
	}
	if !strings.Contains(args, "--kubelet-insecure-tls") {
		if err := l.kubectl(ctx, "patch", "deployment", "metrics-server", "-n", "kube-system",
			"--type=json", "--patch="+patch); err != nil {
			return fmt.Errorf("patching metrics-server: %w", err)
		}
	}
	if err := l.kubectl(ctx, "rollout", "status", "deployment/metrics-server",
		"-n", "kube-system", "--timeout=300s"); err != nil {
		return fmt.Errorf("waiting for metrics-server: %w", err)
	}
	l.Log.OK("Metrics server setup completed")
	return nil
}

func (l *Lab) installNginxIngress(ctx context.Context) error {
	l.Log.Step("Installing NGINX Ingress Controller...")
	if _, err := l.kubectlOutput(ctx, "get", "namespace", "ingress-nginx"); err == nil {
		l.Log.Warn("NGINX Ingress already installed")
		return nil
	}
	if err := l.applyFile(ctx, IngressNginxURL); err != nil {
		return fmt.Errorf("installing NGINX ingress: %w", err)
	}
	if err := l.kubectl(ctx, "wait", "--namespace", "ingress-nginx",
		"--for=condition=ready", "pod",
		"--selector=app.kubernetes.io/component=controller",
		"--timeout=300s"); err != nil {
		return fmt.Errorf("waiting for NGINX ingress: %w", err)
	}
	l.Log.OK("NGINX Ingress Controller installed")
	return nil
}

func (l *Lab) deployMonitoring(ctx context.Context) error {
	l.Log.Step("Deploying monitoring stack...")
	if _, err := l.kubectlOutput(ctx, "get", "deployment", "-n", "monitoring",
		"kube-prometheus-stack-operator"); err == nil {
		l.Log.Warn("Monitoring stack already installed")
		return nil
	}
	if err := l.helm(ctx,
		"upgrade", "--install", "kube-prometheus-stack", "kube-prometheus-stack",
		"--repo", PrometheusChartRepo,
		"--namespace", "monitoring", "--create-namespace",
		"--values", l.Home.Path("config", "monitoring", "prometheus-values.yaml"),
		"--wait", "--timeout", "600s",
	); err != nil {
		return fmt.Errorf("installing monitoring stack: %w", err)
	}
	l.Log.OK("Monitoring stack deployed")
	return nil
}

func (l *Lab) showAccessInfo() {
	l.Log.Section("🎉 Dev Lab deployment completed!")
	l.Log.Plain("%-14s %-28s %s", "Service", "URL", "Credentials")
	l.Log.Plain("%-14s %-28s %s", "Prometheus", "http://localhost:30090", "-")
	l.Log.Plain("%-14s %-28s %s", "Grafana", "http://localhost:30030", "admin/admin123")
	l.Log.Plain("%-14s %-28s %s", "AlertManager", "http://localhost:9093", "-")
	l.Log.Plain("%-14s %-28s %s", "Registry", "http://localhost:5000", "-")
	l.Log.Plain("\nUseful Commands:")
	l.Log.Plain("  bin/devlab status")
	l.Log.Plain("  bin/devlab kubectl get pods -A")
	l.Log.Plain("  bin/devlab linkerd check")
	l.Log.Plain("  bin/devlab test")
}
