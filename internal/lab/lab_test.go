package lab

import (
	"context"
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"golang.org/x/crypto/ssh"
	"gopkg.in/yaml.v3"
)

func TestFindHome(t *testing.T) {
	home := tempHome(t, map[string]string{})
	nested := filepath.Join(home.Root, "config", "gpu")
	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatal(err)
	}
	elsewhere := t.TempDir()

	cases := []struct {
		name                      string
		explicit, executable, cwd string
		wantErr                   bool
	}{
		{"explicit", home.Root, "", elsewhere, false},
		{"binary in home/bin", "", filepath.Join(home.Root, "bin", "devlab"), elsewhere, false},
		{"working directory below home", "", "/usr/local/bin/devlab", nested, false},
		{"explicit non-home", elsewhere, "", home.Root, true},
		{"nothing found", "", "/usr/local/bin/devlab", elsewhere, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			found, err := FindHome(tc.explicit, tc.executable, tc.cwd)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, found %s", found.Root)
				}
				return
			}
			if err != nil || found.Root != home.Root {
				t.Fatalf("FindHome = %q, %v; want %q", found.Root, err, home.Root)
			}
		})
	}
}

func TestToolPrefersBundledBinary(t *testing.T) {
	home := tempHome(t, map[string]string{})
	bundled := home.Path("bin", "kubectl")
	if err := os.MkdirAll(filepath.Dir(bundled), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(bundled, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if got := home.Tool("kubectl"); got != bundled {
		t.Fatalf("Tool(kubectl) = %s, want %s", got, bundled)
	}
}

func TestToolCmdUsesDevLabKubeconfig(t *testing.T) {
	l, _, _, _ := testLab(t)
	cmd := l.kubectlCmd("get", "nodes")
	if !slices.Contains(cmd.Env, "KUBECONFIG="+l.Home.Kubeconfig()) {
		t.Fatalf("env %v has no dev-lab KUBECONFIG", cmd.Env)
	}
	if strings.Join(cmd.Args, " ") != "--context kind-dev-lab get nodes" {
		t.Fatalf("args = %v", cmd.Args)
	}
}

func TestGPUPrerequisites(t *testing.T) {
	t.Run("non-linux", func(t *testing.T) {
		l, runner, _, _ := testLab(t)
		l.GOOS = "darwin"
		if err := l.CheckGPUPrerequisites(context.Background()); err == nil {
			t.Fatal("expected error")
		}
		if len(runner.commands) != 0 {
			t.Fatalf("ran %v", runner.lines())
		}
	})
	t.Run("no nvidia-smi", func(t *testing.T) {
		l, runner, _, _ := testLab(t)
		l.LookPath = func(string) (string, error) { return "", errors.New("not found") }
		if err := l.CheckGPUPrerequisites(context.Background()); err == nil {
			t.Fatal("expected error")
		}
		if len(runner.commands) != 0 {
			t.Fatalf("ran %v", runner.lines())
		}
	})
	t.Run("docker cannot inject GPUs", func(t *testing.T) {
		l, runner, _, out := testLab(t)
		runner.respond = func(cmd Cmd) (string, error) {
			if cmd.Name == "docker" {
				return "", errors.New("could not select device driver")
			}
			if slices.Contains(cmd.Args, "-L") {
				return "GPU 0: NVIDIA A10-24Q (UUID: GPU-1)\n", nil
			}
			return "", nil
		}
		if err := l.CheckGPUPrerequisites(context.Background()); err == nil {
			t.Fatal("expected error")
		}
		if _, ok := runner.find("/dev/null:/var/run/nvidia-container-devices/all"); !ok {
			t.Fatalf("no volume mount check in %v", runner.lines())
		}
		if !strings.Contains(out.String(), "accept-nvidia-visible-devices-as-volume-mounts=true") {
			t.Fatal("setup steps not shown")
		}
	})
}

func TestVGPULicenseWarning(t *testing.T) {
	cases := []struct {
		name, output string
		warns        bool
	}{
		{"bare metal", "Product Name : NVIDIA A10\n", false},
		{"licensed vGPU", "    License Status : Licensed (Expiry: 2026-11-1 0:0:0 GMT)\n", false},
		{"unlicensed vGPU", "    License Status : Unlicensed (Restricted)\n", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			l, runner, _, out := testLab(t)
			runner.respond = func(Cmd) (string, error) { return tc.output, nil }
			l.checkVGPULicense(context.Background())
			if got := strings.Contains(out.String(), "throttled"); got != tc.warns {
				t.Fatalf("warned = %v, want %v: %s", got, tc.warns, out.String())
			}
		})
	}
}

func TestDevicePluginWaitsForGPUCapacity(t *testing.T) {
	l, runner, _, _ := testLab(t)
	nodeChecks := 0
	runner.respond = func(cmd Cmd) (string, error) {
		if slices.Contains(cmd.Args, "nodes") && slices.Contains(cmd.Args, "json") {
			nodeChecks++
			if nodeChecks < 3 {
				return `{"items":[{"metadata":{"name":"dev-lab-worker"},"status":{"allocatable":{"cpu":"8"}}}]}`, nil
			}
			return `{"items":[{"metadata":{"name":"dev-lab-worker"},"status":{"allocatable":{"nvidia.com/gpu":"4"}}}]}`, nil
		}
		return "", nil
	}
	if err := l.SetupGPUDevicePlugin(context.Background()); err != nil {
		t.Fatal(err)
	}
	index, ok := runner.find("helm upgrade --install nvidia-device-plugin")
	if !ok {
		t.Fatalf("no helm install in %v", runner.lines())
	}
	helm := runner.lines()[index]
	for _, want := range []string{"--version " + NvidiaDevicePluginVersion, "config/gpu/nvidia-device-plugin-values.yaml", "--kube-context kind-dev-lab"} {
		if !strings.Contains(helm, want) {
			t.Errorf("helm command %q missing %q", helm, want)
		}
	}
	if nodeChecks != 3 {
		t.Fatalf("checked nodes %d times, want 3", nodeChecks)
	}
}

func TestDevicePluginFailsWithoutGPUCapacity(t *testing.T) {
	l, runner, _, out := testLab(t)
	runner.respond = func(cmd Cmd) (string, error) {
		if slices.Contains(cmd.Args, "json") {
			return `{"items":[{"metadata":{"name":"dev-lab-worker"},"status":{"allocatable":{"nvidia.com/gpu":"0"}}}]}`, nil
		}
		return "", nil
	}
	if err := l.SetupGPUDevicePlugin(context.Background()); err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(out.String(), "bin/devlab cleanup && bin/devlab bootstrap --gpu") {
		t.Fatal("rebuild hint missing")
	}
}

func TestRenderNvkindConfigKeepsKindConfigShape(t *testing.T) {
	l, _, _, _ := testLab(t)
	l.Run = &fakeRunner{respond: func(Cmd) (string, error) { return "GPU 0: NVIDIA A10\n", nil }}
	config, gpuNodes, err := l.renderGPUClusterConfig(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(gpuNodes) != 1 || gpuNodes[0].name != "dev-lab-worker" || !slices.Equal(gpuNodes[0].devices, []string{"all"}) {
		t.Fatalf("gpu nodes = %+v", gpuNodes)
	}

	rendered := withoutWorkers(t, config)
	kindConfig, err := os.ReadFile(l.Home.Path("cluster", "kind-config.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	original := withoutWorkers(t, kindConfig)
	renderedYAML, _ := yaml.Marshal(rendered)
	originalYAML, _ := yaml.Marshal(original)
	if string(renderedYAML) != string(originalYAML) {
		t.Fatalf("nvkind template drifted from kind-config.yaml:\n%s\n---\n%s", renderedYAML, originalYAML)
	}

	var cluster map[string]any
	if err := yaml.Unmarshal(config, &cluster); err != nil {
		t.Fatal(err)
	}
	workers := 0
	for _, node := range cluster["nodes"].([]any) {
		if node.(map[string]any)["role"] == "worker" {
			workers++
		}
	}
	if workers != 2 {
		t.Fatalf("workers = %d, want 2", workers)
	}
}

func withoutWorkers(t *testing.T, config []byte) map[string]any {
	t.Helper()
	var cluster map[string]any
	if err := yaml.Unmarshal(config, &cluster); err != nil {
		t.Fatal(err)
	}
	var nodes []any
	for _, node := range cluster["nodes"].([]any) {
		if node.(map[string]any)["role"] != "worker" {
			nodes = append(nodes, node)
		}
	}
	cluster["nodes"] = nodes
	return cluster
}

func TestRenderNvkindConfigPerWorkerDevices(t *testing.T) {
	root := repoRoot(t)
	templateText, err := os.ReadFile(filepath.Join(root, "cluster", "nvkind-config-template.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	values := []byte("workers:\n- devices: 0\n- {}\n- devices: [1, 2]\n")
	config, err := RenderNvkindConfig(string(templateText), values, func() (int, error) { return 3, nil })
	if err != nil {
		t.Fatal(err)
	}
	nodes, err := gpuNodesFromConfig(config)
	if err != nil {
		t.Fatal(err)
	}
	want := []gpuNode{{"dev-lab-worker", []string{"0"}}, {"dev-lab-worker3", []string{"1", "2"}}}
	if len(nodes) != len(want) {
		t.Fatalf("nodes = %+v", nodes)
	}
	for i := range want {
		if nodes[i].name != want[i].name || !slices.Equal(nodes[i].devices, want[i].devices) {
			t.Fatalf("nodes = %+v, want %+v", nodes, want)
		}
	}
}

func TestSetupGPUNodesRemovesUnassignedDevices(t *testing.T) {
	l, runner, cluster, _ := testLab(t)
	runner.respond = func(Cmd) (string, error) { return "GPU 0: A\nGPU 1: B\n", nil }
	worker := &fakeNode{name: "dev-lab-worker", params: "ModifyDeviceFiles: 0\n"}
	cluster.nodes = []*fakeNode{{name: "dev-lab-control-plane"}, worker}

	if err := l.setupGPUNodes(context.Background(), []gpuNode{{"dev-lab-worker", []string{"0"}}}); err != nil {
		t.Fatal(err)
	}
	joined := strings.Join(worker.scripts, "\n")
	for _, want := range []string{"apt-get install -y nvidia-container-toolkit", "nvidia-ctk runtime configure --runtime=containerd", "rm -rf /dev/nvidia1"} {
		if !strings.Contains(joined, want) {
			t.Errorf("node scripts missing %q", want)
		}
	}
	if strings.Contains(joined, "rm -rf /dev/nvidia0") {
		t.Error("removed the assigned GPU")
	}
	if strings.Contains(joined, "umount -R /proc/driver/nvidia") {
		t.Error("patched params that were already masked")
	}
}

func TestBootstrapGPUOrder(t *testing.T) {
	l, runner, cluster, _ := testLab(t)
	cluster.nodes = []*fakeNode{{name: "dev-lab-worker", params: "ModifyDeviceFiles: 0\n"}}
	runner.respond = func(cmd Cmd) (string, error) {
		switch {
		case slices.Contains(cmd.Args, "-L"):
			return "GPU 0: NVIDIA A10-24Q (UUID: GPU-1)\n", nil
		case slices.Contains(cmd.Args, "json"):
			return `{"items":[{"metadata":{"name":"dev-lab-worker"},"status":{"allocatable":{"nvidia.com/gpu":"4"}}}]}`, nil
		}
		return "", nil
	}
	if err := l.Bootstrap(context.Background(), BootstrapOptions{GPU: true}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(cluster.created), "/var/run/nvidia-container-devices/all") {
		t.Fatalf("cluster not created from the nvkind template:\n%s", cluster.created)
	}
	order := []string{"/dev/null:/var/run/nvidia-container-devices/all", "wait --for=condition=Ready nodes",
		"helm upgrade --install nvidia-device-plugin", "linkerd check --pre", "linkerd viz install"}
	last := -1
	for _, step := range order {
		index, ok := runner.find(step)
		if !ok || index < last {
			t.Fatalf("step %q out of order in:\n%s", step, strings.Join(runner.lines(), "\n"))
		}
		last = index
	}
}

func TestBootstrapKeepsExistingClusterWhenNotInteractive(t *testing.T) {
	l, _, cluster, _ := testLab(t)
	cluster.exists = true
	if err := l.createCluster(context.Background(), BootstrapOptions{}); err != nil {
		t.Fatal(err)
	}
	if cluster.deleted || cluster.created != nil {
		t.Fatal("recreated the cluster without confirmation")
	}
	if err := l.createCluster(context.Background(), BootstrapOptions{Recreate: true}); err != nil {
		t.Fatal(err)
	}
	if !cluster.deleted || cluster.created == nil {
		t.Fatal("--recreate did not recreate the cluster")
	}
}

func TestDeployKey(t *testing.T) {
	private, public, err := NewDeployKey("flux-dev-lab-test")
	if err != nil {
		t.Fatal(err)
	}
	signer, err := ssh.ParsePrivateKey(private)
	if err != nil {
		t.Fatal(err)
	}
	parsed, comment, _, _, err := ssh.ParseAuthorizedKey([]byte(public))
	if err != nil {
		t.Fatal(err)
	}
	if comment != "flux-dev-lab-test" || string(parsed.Marshal()) != string(signer.PublicKey().Marshal()) {
		t.Fatal("public key does not match private key")
	}
}

func TestFluxSecretManifest(t *testing.T) {
	manifest := fluxSecretManifest([]byte("private"), []byte("public"), "github.com ssh-ed25519 AAAA\n")
	var secret struct {
		Metadata struct {
			Name, Namespace string
		}
		Data map[string]string
	}
	if err := yaml.Unmarshal([]byte(manifest), &secret); err != nil {
		t.Fatal(err)
	}
	if secret.Metadata.Name != "flux-system-auth" || secret.Metadata.Namespace != "flux-system" {
		t.Fatalf("metadata = %+v", secret.Metadata)
	}
	for key, want := range map[string]string{"identity": "private", "identity.pub": "public", "known_hosts": "github.com ssh-ed25519 AAAA\n"} {
		got, _ := base64.StdEncoding.DecodeString(secret.Data[key])
		if string(got) != want {
			t.Errorf("%s = %q, want %q", key, got, want)
		}
	}
}

func TestGitRepositoryURL(t *testing.T) {
	l, _, _, _ := testLab(t)
	manifest, err := l.gitRepositoryManifest("")
	if err != nil {
		t.Fatal(err)
	}
	url := gitRepositoryURL(manifest)
	if url != "ssh://git@github.com/jbotstevens/dev-lab.git" {
		t.Fatalf("url = %s", url)
	}
	if sshHost(url) != "github.com" || repoWebURL(url) != "https://github.com/jbotstevens/dev-lab" {
		t.Fatalf("host %s, web %s", sshHost(url), repoWebURL(url))
	}
	override, err := l.gitRepositoryManifest("git@gitlab.example.com:me/lab.git")
	if err != nil {
		t.Fatal(err)
	}
	if gitRepositoryURL(override) != "git@gitlab.example.com:me/lab.git" || sshHost(gitRepositoryURL(override)) != "gitlab.example.com" {
		t.Fatalf("override not applied:\n%s", override)
	}
}

func TestLoadImagesSelectsNodes(t *testing.T) {
	l, runner, cluster, _ := testLab(t)
	control := &fakeNode{name: "dev-lab-control-plane"}
	worker := &fakeNode{name: "dev-lab-worker"}
	cluster.nodes = []*fakeNode{control, worker}
	if err := l.LoadImages(context.Background(), []string{"app:latest"}, []string{"dev-lab-worker"}); err != nil {
		t.Fatal(err)
	}
	if control.archives != 0 || worker.archives != 1 {
		t.Fatalf("archives: control %d, worker %d", control.archives, worker.archives)
	}
	if _, ok := runner.find("docker save -o"); !ok {
		t.Fatalf("no docker save in %v", runner.lines())
	}
	if err := l.LoadImages(context.Background(), []string{"app:latest"}, []string{"nope"}); err == nil {
		t.Fatal("expected error for unknown node")
	}
}

func TestScanHostKeysLive(t *testing.T) {
	if os.Getenv("DEVLAB_LIVE") == "" {
		t.Skip("set DEVLAB_LIVE=1 to scan github.com")
	}
	lines, err := ScanHostKeys(context.Background(), "github.com")
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range lines {
		t.Log(line)
		if !strings.HasPrefix(line, "github.com ") {
			t.Errorf("bad known_hosts line %q", line)
		}
	}
	if len(lines) < 2 {
		t.Fatalf("got %d host keys", len(lines))
	}
}
