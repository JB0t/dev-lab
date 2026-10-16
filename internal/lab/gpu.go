package lab

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"text/template"
	"time"

	"github.com/Masterminds/sprig/v3"
	"gopkg.in/yaml.v3"
	"sigs.k8s.io/kind/pkg/apis/config/v1alpha4"
	sigsyaml "sigs.k8s.io/yaml"
)

var lookPath = exec.LookPath

// nvkind injects GPUs into kind nodes by mounting /dev/null at these paths;
// the host nvidia-container-runtime turns each mount into a GPU.
const nvidiaDevicesDir = "/var/run/nvidia-container-devices"

// CheckGPUPrerequisites checks the host can run a GPU-enabled kind cluster.
func (l *Lab) CheckGPUPrerequisites(ctx context.Context) error {
	l.Log.Step("Checking GPU prerequisites...")

	if l.GOOS != "linux" {
		return fmt.Errorf("--gpu needs a Linux host (or WSL2) with an NVIDIA GPU")
	}
	if _, err := l.LookPath("nvidia-smi"); err != nil {
		return fmt.Errorf("nvidia-smi not found: install the NVIDIA driver (vGPU guests: the vGPU guest driver)")
	}

	gpus, err := l.Run.Output(ctx, Cmd{Name: "nvidia-smi", Args: []string{"-L"}})
	if err != nil || strings.TrimSpace(gpus) == "" {
		return fmt.Errorf("nvidia-smi found no GPUs: %v", err)
	}
	l.Log.Info("Host GPUs:\n%s", strings.TrimSpace(gpus))
	l.checkVGPULicense(ctx)

	// nvkind injects GPUs into kind nodes through /dev/null volume mounts
	l.Log.Step("Checking Docker can inject GPUs via volume mounts...")
	if _, err := l.Run.Output(ctx, Cmd{Name: "docker", Args: []string{
		"run", "--rm",
		"-v", "/dev/null:" + nvidiaDevicesDir + "/all",
		"ubuntu:22.04", "nvidia-smi", "-L",
	}}); err != nil {
		l.Log.Fail("Docker cannot inject GPUs into containers: %v", err)
		l.Log.Warn("Configure the NVIDIA Container Toolkit for GPU-enabled kind, then retry:")
		l.Log.Plain("  sudo nvidia-ctk runtime configure --runtime=docker --set-as-default --cdi.enabled")
		l.Log.Plain("  sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place")
		l.Log.Plain("  sudo systemctl restart docker")
		return fmt.Errorf("docker GPU injection check failed")
	}

	l.Log.OK("GPU prerequisites met")
	return nil
}

var licenseStatus = regexp.MustCompile(`(?m)^\s*License Status\s*:\s*(.+?)\s*$`)

// checkVGPULicense warns when a vGPU guest has no license (NVIDIA throttles
// it after 20 minutes). Bare-metal GPUs report no license status.
func (l *Lab) checkVGPULicense(ctx context.Context) {
	output, err := l.Run.Output(ctx, Cmd{Name: "nvidia-smi", Args: []string{"-q"}})
	if err != nil {
		return
	}
	for _, match := range licenseStatus.FindAllStringSubmatch(output, -1) {
		if !strings.HasPrefix(match[1], "Licensed") {
			l.Log.Warn("vGPU license status: %s", match[1])
			l.Log.Warn("Unlicensed vGPUs are throttled after 20 minutes. See the vGPU section of README.md to license this VM.")
			return
		}
	}
}

// numGPUs counts host GPUs (the nvkind template function of the same name).
func (l *Lab) numGPUs(ctx context.Context) (int, error) {
	output, err := l.Run.Output(ctx, Cmd{Name: "nvidia-smi", Args: []string{"-L"}})
	if err != nil {
		return 0, err
	}
	count := 0
	for _, line := range strings.Split(output, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "GPU ") {
			count++
		}
	}
	return count, nil
}

// gpuNode is a kind worker with GPUs and the devices mounted into it.
type gpuNode struct {
	name    string
	devices []string // GPU indexes or "all"
}

// renderGPUClusterConfig renders cluster/nvkind-config-template.yaml with
// cluster/nvkind-values.yaml, the way `nvkind cluster create` does: a Go
// template with sprig functions and numGPUs.
func (l *Lab) renderGPUClusterConfig(ctx context.Context) ([]byte, []gpuNode, error) {
	templateText, err := os.ReadFile(l.Home.Path("cluster", "nvkind-config-template.yaml"))
	if err != nil {
		return nil, nil, err
	}
	valuesText, err := os.ReadFile(l.Home.Path("cluster", "nvkind-values.yaml"))
	if err != nil {
		return nil, nil, err
	}
	config, err := RenderNvkindConfig(string(templateText), valuesText, func() (int, error) { return l.numGPUs(ctx) })
	if err != nil {
		return nil, nil, err
	}
	nodes, err := gpuNodesFromConfig(config)
	if err != nil {
		return nil, nil, err
	}
	return config, nodes, nil
}

// RenderNvkindConfig renders an nvkind config template with its values.
func RenderNvkindConfig(templateText string, valuesYAML []byte, numGPUs func() (int, error)) ([]byte, error) {
	funcs := sprig.TxtFuncMap()
	funcs["numGPUs"] = numGPUs
	tmpl, err := template.New("nvkind-config").Funcs(funcs).Parse(templateText)
	if err != nil {
		return nil, fmt.Errorf("parsing nvkind config template: %w", err)
	}
	var values map[string]any
	if err := yaml.Unmarshal(valuesYAML, &values); err != nil {
		return nil, fmt.Errorf("parsing nvkind values: %w", err)
	}
	var rendered bytes.Buffer
	if err := tmpl.Execute(&rendered, values); err != nil {
		return nil, fmt.Errorf("rendering nvkind config template: %w", err)
	}
	return rendered.Bytes(), nil
}

// gpuNodesFromConfig maps each worker with GPU mounts to its kind node
// name: kind names workers <cluster>-worker, <cluster>-worker2, ... in
// config order.
func gpuNodesFromConfig(config []byte) ([]gpuNode, error) {
	var cluster v1alpha4.Cluster
	if err := sigsyaml.Unmarshal(config, &cluster); err != nil {
		return nil, fmt.Errorf("parsing rendered cluster config: %w", err)
	}
	var nodes []gpuNode
	worker := 0
	for _, node := range cluster.Nodes {
		if node.Role != v1alpha4.WorkerRole {
			continue
		}
		worker++
		name := ClusterName + "-worker"
		if worker > 1 {
			name += strconv.Itoa(worker)
		}
		var devices []string
		for _, mount := range node.ExtraMounts {
			if mount.HostPath == "/dev/null" && path.Dir(mount.ContainerPath) == nvidiaDevicesDir {
				devices = append(devices, path.Base(mount.ContainerPath))
			}
		}
		if len(devices) > 0 {
			nodes = append(nodes, gpuNode{name: name, devices: devices})
		}
	}
	if len(nodes) == 0 {
		return nil, fmt.Errorf("cluster/nvkind-values.yaml gives no worker any GPU devices")
	}
	return nodes, nil
}

// The node setup scripts below are adapted from nvkind's pkg/nvkind/node.go
// (https://github.com/NVIDIA/nvkind, Apache-2.0). nvkind itself is not used
// because its NVML bindings need cgo.

const installToolkitScript = `
set -e
apt-get update
apt-get install -y gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
	sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
	tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
apt-get install -y nvidia-container-toolkit
`

const configureRuntimeScript = `
set -e
nvidia-ctk runtime configure --runtime=containerd --config-source=file
systemctl restart containerd
`

// Toolkits older than v1.19.0 bind-mount a tmpfs over /proc/driver/nvidia,
// hiding the real params file. Expose it, set ModifyDeviceFiles to 0 and
// bind-mount the copy back, so the driver does not recreate device nodes.
const patchProcDriverScript = `
set -e
umount -R /proc/driver/nvidia
cp /proc/driver/nvidia/params root/gpu-params
sed -i 's/^ModifyDeviceFiles: 1$/ModifyDeviceFiles: 0/' root/gpu-params
mount --bind root/gpu-params /proc/driver/nvidia/params
`

const removeDeviceNodeScript = `
while umount /dev/nvidia%[1]d; do :; done || true
rm -rf /dev/nvidia%[1]d
`

// setupGPUNodes installs the NVIDIA Container Toolkit in each GPU worker
// and adds the nvidia runtime to its containerd.
func (l *Lab) setupGPUNodes(ctx context.Context, gpuNodes []gpuNode) error {
	nodes, err := l.Cluster.Nodes(ClusterName)
	if err != nil {
		return fmt.Errorf("listing cluster nodes: %w", err)
	}
	byName := map[string]Node{}
	for _, node := range nodes {
		byName[node.Name()] = node
	}
	hostGPUs := -1

	for _, gpu := range gpuNodes {
		node, ok := byName[gpu.name]
		if !ok {
			return fmt.Errorf("GPU worker %s not found in the cluster", gpu.name)
		}
		l.Log.Step("Setting up GPUs on %s (devices: %s)...", gpu.name, strings.Join(gpu.devices, ","))

		if err := l.nodeScript(node, installToolkitScript); err != nil {
			return fmt.Errorf("installing NVIDIA Container Toolkit on %s: %w", gpu.name, err)
		}
		if err := l.nodeScript(node, configureRuntimeScript); err != nil {
			return fmt.Errorf("configuring containerd on %s: %w", gpu.name, err)
		}

		// Failures here are warnings, like nvkind's benign umount errors:
		// the device plugin capacity check catches a broken node.
		masked, err := modifyDeviceFilesDisabled(node)
		if err != nil {
			l.Log.Warn("Could not read /proc/driver/nvidia/params on %s: %v", gpu.name, err)
		} else if !masked {
			if err := l.nodeScript(node, patchProcDriverScript); err != nil {
				l.Log.Warn("Could not mask /proc/driver/nvidia/params on %s: %v", gpu.name, err)
			}
		}

		// The node inherits every host /dev/nvidiaN; remove the ones it was not given
		if slices.Contains(gpu.devices, "all") {
			continue
		}
		if hostGPUs < 0 {
			if hostGPUs, err = l.numGPUs(ctx); err != nil {
				return fmt.Errorf("counting host GPUs: %w", err)
			}
		}
		for index := 0; index < hostGPUs; index++ {
			if slices.Contains(gpu.devices, strconv.Itoa(index)) {
				continue
			}
			if err := l.nodeScript(node, fmt.Sprintf(removeDeviceNodeScript, index)); err != nil {
				l.Log.Warn("Could not remove /dev/nvidia%d from %s: %v", index, gpu.name, err)
			}
		}
	}
	return nil
}

func (l *Lab) nodeScript(node Node, script string) error {
	return node.Exec(nil, l.Log.Out, l.Log.Out, "bash", "-c", script)
}

// modifyDeviceFilesDisabled reports whether /proc/driver/nvidia/params in
// the node already reads `ModifyDeviceFiles: 0`, which toolkit v1.19.0+
// sets up itself through a CDI hook.
func modifyDeviceFilesDisabled(node Node) (bool, error) {
	var params bytes.Buffer
	if err := node.Exec(nil, &params, nil, "cat", "/proc/driver/nvidia/params"); err != nil {
		return false, err
	}
	for _, line := range strings.Split(params.String(), "\n") {
		switch strings.TrimSpace(line) {
		case "ModifyDeviceFiles: 0":
			return true, nil
		case "ModifyDeviceFiles: 1":
			return false, nil
		}
	}
	return false, fmt.Errorf("no ModifyDeviceFiles line")
}

// SetupGPUDevicePlugin installs the NVIDIA device plugin (with the
// time-slicing config) and waits until GPUs are allocatable.
func (l *Lab) SetupGPUDevicePlugin(ctx context.Context) error {
	l.Log.Step("Setting up NVIDIA device plugin...")

	if err := l.applyFile(ctx, l.Home.Path("config", "gpu", "nvidia-runtimeclass.yaml")); err != nil {
		return fmt.Errorf("applying nvidia RuntimeClass: %w", err)
	}
	if err := l.helm(ctx,
		"upgrade", "--install", "nvidia-device-plugin", "nvidia-device-plugin",
		"--repo", NvidiaDevicePluginRepo,
		"--version", NvidiaDevicePluginVersion,
		"--namespace", "nvidia", "--create-namespace",
		"--values", l.Home.Path("config", "gpu", "nvidia-device-plugin-values.yaml"),
		"--wait", "--timeout", "300s",
	); err != nil {
		return fmt.Errorf("installing NVIDIA device plugin: %w", err)
	}

	// The plugin registers GPUs with the kubelet shortly after it starts
	l.Log.Step("Waiting for GPUs to be allocatable...")
	for attempt := 0; attempt < 60; attempt++ {
		if output, err := l.kubectlOutput(ctx, "get", "nodes", "-o", "json"); err == nil {
			if gpus, err := allocatableGPUs(output); err == nil && len(gpus) > 0 {
				for _, node := range gpus {
					l.Log.Info("%s: %s allocatable nvidia.com/gpu", node.name, node.gpus)
				}
				l.Log.OK("NVIDIA device plugin setup completed")
				return nil
			}
		}
		l.Sleep(2 * time.Second)
	}

	l.Log.Fail("No node advertised nvidia.com/gpu capacity")
	l.Log.Warn("Check: bin/devlab kubectl -- logs -n nvidia -l app.kubernetes.io/name=nvidia-device-plugin -c nvidia-device-plugin-ctr")
	l.Log.Warn("If you kept an existing cluster created without --gpu, delete it and re-bootstrap: " +
		"bin/devlab cleanup && bin/devlab bootstrap --gpu")
	return fmt.Errorf("no allocatable GPUs")
}

type nodeGPUs struct {
	name string
	gpus string
}

type nodeList struct {
	Items []struct {
		Metadata struct {
			Name   string            `json:"name"`
			Labels map[string]string `json:"labels"`
		} `json:"metadata"`
		Status struct {
			Allocatable map[string]string `json:"allocatable"`
			Conditions  []struct {
				Type   string `json:"type"`
				Status string `json:"status"`
			} `json:"conditions"`
		} `json:"status"`
	} `json:"items"`
}

// allocatableGPUs lists nodes with non-zero allocatable nvidia.com/gpu.
func allocatableGPUs(nodesJSON string) ([]nodeGPUs, error) {
	var nodes nodeList
	if err := json.Unmarshal([]byte(nodesJSON), &nodes); err != nil {
		return nil, err
	}
	var result []nodeGPUs
	for _, node := range nodes.Items {
		if count := node.Status.Allocatable["nvidia.com/gpu"]; count != "" && count != "0" {
			result = append(result, nodeGPUs{name: node.Metadata.Name, gpus: count})
		}
	}
	return result, nil
}
