package lab

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// Status prints Docker, cluster and node status.
func (l *Lab) Status(ctx context.Context) error {
	l.Log.Section("Dev Lab Status")
	if err := l.CheckDocker(ctx); err != nil {
		l.Log.Fail("❌ Docker is not available")
		return err
	}
	l.Log.OK("Docker is running")

	if !l.clusterReachable(ctx) {
		l.Log.Fail("❌ Cluster is not accessible")
		return fmt.Errorf("cluster %s is not accessible", ClusterName)
	}
	l.Log.OK("Cluster is accessible (kubeconfig: %s)", l.Home.Kubeconfig())

	output, err := l.kubectlOutput(ctx, "get", "nodes", "-o", "json")
	if err != nil {
		return err
	}
	var nodes nodeList
	if err := json.Unmarshal([]byte(output), &nodes); err != nil {
		return err
	}
	l.Log.Plain("\n%-28s %-9s %-14s %s", "NAME", "STATUS", "ROLE", "GPUS")
	for _, node := range nodes.Items {
		status := "NotReady"
		for _, condition := range node.Status.Conditions {
			if condition.Type == "Ready" && condition.Status == "True" {
				status = "Ready"
			}
		}
		role := "worker"
		if _, ok := node.Metadata.Labels["node-role.kubernetes.io/control-plane"]; ok {
			role = "control-plane"
		}
		gpus := node.Status.Allocatable["nvidia.com/gpu"]
		if gpus == "" {
			gpus = "-"
		}
		l.Log.Plain("%-28s %-9s %-14s %s", node.Metadata.Name, status, role, gpus)
	}
	return nil
}

// Cleanup deletes the dev-lab cluster.
func (l *Lab) Cleanup(ctx context.Context, yes bool) error {
	exists, err := l.Cluster.Exists(ClusterName)
	if err != nil {
		return err
	}
	if !exists {
		l.Log.Warn("Cluster '%s' does not exist", ClusterName)
		return nil
	}
	if !yes && !l.confirm("This will delete the entire dev-lab cluster. Continue?") {
		return nil
	}
	l.Log.Step("Cleaning up dev-lab environment...")
	if err := l.Cluster.Delete(ClusterName, l.Home.Kubeconfig()); err != nil {
		return fmt.Errorf("deleting cluster: %w", err)
	}
	l.Log.OK("Cleanup completed")
	return nil
}

// LoadImages copies local Docker images into the cluster nodes (what
// `kind load docker-image --name dev-lab` did). nodeNames limits the nodes.
func (l *Lab) LoadImages(ctx context.Context, images, nodeNames []string) error {
	nodes, err := l.Cluster.Nodes(ClusterName)
	if err != nil {
		return fmt.Errorf("listing cluster nodes: %w", err)
	}
	if len(nodeNames) > 0 {
		var selected []Node
		for _, name := range nodeNames {
			found := false
			for _, node := range nodes {
				if node.Name() == name {
					selected = append(selected, node)
					found = true
				}
			}
			if !found {
				return fmt.Errorf("node %s is not part of cluster %s", name, ClusterName)
			}
		}
		nodes = selected
	}

	archive, err := os.CreateTemp("", "devlab-images-*.tar")
	if err != nil {
		return err
	}
	defer os.Remove(archive.Name())
	archive.Close()

	l.Log.Step("Saving %s...", strings.Join(images, ", "))
	if err := l.Run.Run(ctx, Cmd{Name: "docker", Args: append([]string{"save", "-o", archive.Name()}, images...)}); err != nil {
		return fmt.Errorf("saving images (are they built or pulled locally?): %w", err)
	}
	for _, node := range nodes {
		l.Log.Step("Loading into %s...", node.Name())
		file, err := os.Open(archive.Name())
		if err != nil {
			return err
		}
		err = node.LoadImageArchive(file)
		file.Close()
		if err != nil {
			return fmt.Errorf("loading images into %s: %w", node.Name(), err)
		}
	}
	l.Log.OK("Loaded %d image(s) into %d node(s)", len(images), len(nodes))
	return nil
}

const testAppManifest = `apiVersion: apps/v1
kind: Deployment
metadata:
  name: devlab-test-app
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: devlab-test-app
  template:
    metadata:
      labels:
        app: devlab-test-app
    spec:
      containers:
        - name: web
          image: devlab-test-app:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
`

const testAppDockerfile = `FROM nginx:alpine
RUN echo '<h1>Dev Lab Test</h1><p>Image built and loaded successfully!</p>' > /usr/share/nginx/html/index.html
`

// Test checks a deployed environment end to end: cluster, nodes, registry,
// monitoring, ingress, and building, loading and running an image.
func (l *Lab) Test(ctx context.Context) error {
	l.Log.Section("🧪 Testing Dev Lab Environment")
	failures := 0
	fail := func(format string, args ...any) {
		failures++
		l.Log.Fail("❌ "+format, args...)
	}

	if !l.clusterReachable(ctx) {
		return fmt.Errorf("cluster is not reachable")
	}
	l.Log.OK("Cluster is reachable")

	if err := l.kubectl(ctx, "wait", "--for=condition=Ready", "nodes", "--all", "--timeout=30s"); err != nil {
		fail("Some nodes are not ready")
	} else {
		l.Log.OK("All nodes are ready")
	}

	if err := httpOK(ctx, "http://localhost:5000/v2/_catalog"); err != nil {
		fail("Registry is not accessible at localhost:5000: %v", err)
	} else {
		l.Log.OK("Registry is accessible")
	}

	for _, check := range []struct{ namespace, name string }{
		{"monitoring", "Monitoring stack"},
		{"ingress-nginx", "Ingress controller"},
	} {
		pods, err := l.kubectlOutput(ctx, "get", "pods", "-n", check.namespace,
			"--field-selector=status.phase=Running", "-o", "name")
		if err != nil || strings.TrimSpace(pods) == "" {
			fail("%s has no running pods (namespace %s)", check.name, check.namespace)
		} else {
			l.Log.OK("%s is running", check.name)
		}
	}

	l.Log.Step("Building and loading a test image...")
	if err := l.Run.Run(ctx, Cmd{Name: "docker", Args: []string{"build", "-t", "devlab-test-app:latest", "-"},
		Stdin: strings.NewReader(testAppDockerfile)}); err != nil {
		fail("Failed to build test image: %v", err)
		return fmt.Errorf("%d check(s) failed", failures)
	}
	if err := l.LoadImages(ctx, []string{"devlab-test-app:latest"}, nil); err != nil {
		fail("Failed to load test image: %v", err)
		return fmt.Errorf("%d check(s) failed", failures)
	}

	l.Log.Step("Deploying test application...")
	defer func() {
		_ = l.Run.Run(ctx, l.kubectlCmd("delete", "deployment", "devlab-test-app", "-n", "default", "--ignore-not-found"))
	}()
	if err := l.applyManifest(ctx, testAppManifest); err != nil {
		fail("Failed to deploy test application: %v", err)
	} else if err := l.kubectl(ctx, "rollout", "status", "deployment/devlab-test-app",
		"-n", "default", "--timeout=120s"); err != nil {
		fail("Test application did not become ready")
	} else {
		l.Log.OK("Test application is running from a loaded image")
	}

	if failures > 0 {
		return fmt.Errorf("%d check(s) failed", failures)
	}
	l.Log.OK("All environment tests passed")
	return nil
}

func httpOK(ctx context.Context, url string) error {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, response.Body)
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d", response.StatusCode)
	}
	return nil
}
