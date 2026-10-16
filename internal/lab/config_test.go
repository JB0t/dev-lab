package lab

// Checks that the shipped GPU sharing config and Dask manifests agree with
// each other (ported from the Python test_gpu_sharing.py).

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

const gib = 1 << 30

// A10-24Q vGPU framebuffer; the workers' fixed RMM pools must leave headroom
// for CUDA contexts and vGPU-reserved memory.
const (
	a10Bytes      = 24_000_000_000
	headroomBytes = 4 * gib
)

func readYAML(t *testing.T, path string, into any) {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := yaml.Unmarshal(data, into); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
}

func readDocuments(t *testing.T, path string) []map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	decoder := yaml.NewDecoder(bytes.NewReader(data))
	var docs []map[string]any
	for {
		var doc map[string]any
		if err := decoder.Decode(&doc); errors.Is(err, io.EOF) {
			break
		} else if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		if doc != nil {
			docs = append(docs, doc)
		}
	}
	return docs
}

// dig walks nested maps and lists: dig(doc, "spec", "template", 0)
func dig(value any, keys ...any) any {
	for _, key := range keys {
		switch k := key.(type) {
		case string:
			value = value.(map[string]any)[k]
		case int:
			value = value.([]any)[k]
		}
	}
	return value
}

type devicePluginValues struct {
	RuntimeClassName string `yaml:"runtimeClassName"`
	Config           struct {
		Default string            `yaml:"default"`
		Map     map[string]string `yaml:"map"`
	} `yaml:"config"`
}

type sharingConfig struct {
	Version string `yaml:"version"`
	Sharing *struct {
		TimeSlicing struct {
			RenameByDefault            bool  `yaml:"renameByDefault"`
			FailRequestsGreaterThanOne *bool `yaml:"failRequestsGreaterThanOne"`
			Resources                  []struct {
				Name     string `yaml:"name"`
				Replicas int    `yaml:"replicas"`
			} `yaml:"resources"`
		} `yaml:"timeSlicing"`
	} `yaml:"sharing"`
}

func loadDevicePluginValues(t *testing.T) (devicePluginValues, map[string]sharingConfig) {
	t.Helper()
	var values devicePluginValues
	readYAML(t, filepath.Join(repoRoot(t), "config", "gpu", "nvidia-device-plugin-values.yaml"), &values)
	configs := map[string]sharingConfig{}
	for name, text := range values.Config.Map {
		var config sharingConfig
		if err := yaml.Unmarshal([]byte(text), &config); err != nil {
			t.Fatalf("config %s: %v", name, err)
		}
		configs[name] = config
	}
	return values, configs
}

func timeSlicingReplicas(t *testing.T) int {
	t.Helper()
	values, configs := loadDevicePluginValues(t)
	resources := configs[values.Config.Default].Sharing.TimeSlicing.Resources
	if len(resources) != 1 || resources[0].Name != "nvidia.com/gpu" {
		t.Fatalf("resources = %+v", resources)
	}
	return resources[0].Replicas
}

func TestTimeSlicingDefaultsToFourSharesPerGPU(t *testing.T) {
	values, configs := loadDevicePluginValues(t)
	if values.Config.Default != "time-sliced" || values.RuntimeClassName != "nvidia" {
		t.Fatalf("values = %+v", values)
	}
	if replicas := timeSlicingReplicas(t); replicas != 4 {
		t.Fatalf("replicas = %d, want 4", replicas)
	}
	sliced := configs["time-sliced"].Sharing.TimeSlicing
	if sliced.RenameByDefault || sliced.FailRequestsGreaterThanOne == nil || !*sliced.FailRequestsGreaterThanOne {
		t.Fatalf("time slicing = %+v", sliced)
	}
	exclusive, ok := configs["exclusive"]
	if !ok || exclusive.Version != "v1" || exclusive.Sharing != nil {
		t.Fatalf("exclusive config = %+v", exclusive)
	}
}

func flagValue(t *testing.T, args []any, flag string) string {
	t.Helper()
	for i, arg := range args {
		if arg == flag && i+1 < len(args) {
			return args[i+1].(string)
		}
	}
	t.Fatalf("flag %s not in %v", flag, args)
	return ""
}

func parseSize(t *testing.T, text string) float64 {
	t.Helper()
	number, ok := strings.CutSuffix(text, "GiB")
	if !ok {
		t.Fatalf("size %q is not in GiB", text)
	}
	value, err := strconv.ParseFloat(number, 64)
	if err != nil {
		t.Fatal(err)
	}
	return value * gib
}

func TestDaskWorkersMatchTimeSlicing(t *testing.T) {
	root := repoRoot(t)
	workers := readDocuments(t, filepath.Join(root, "config", "dask", "workers.yaml"))[0]
	replicas := dig(workers, "spec", "replicas").(int)
	if replicas != timeSlicingReplicas(t) {
		t.Fatalf("worker replicas %d != time-slicing replicas %d", replicas, timeSlicingReplicas(t))
	}
	pod := dig(workers, "spec", "template", "spec")
	if dig(pod, "runtimeClassName") != "nvidia" {
		t.Fatal("workers are not using the nvidia runtime")
	}
	container := dig(pod, "containers", 0)
	if gpus := dig(container, "resources", "limits", "nvidia.com/gpu"); gpus != 1 {
		t.Fatalf("worker nvidia.com/gpu = %v, want 1", gpus)
	}

	args := dig(container, "args").([]any)
	pool := parseSize(t, flagValue(t, args, "--rmm-pool-size"))
	maximum := parseSize(t, flagValue(t, args, "--rmm-maximum-pool-size"))
	spill := parseSize(t, flagValue(t, args, "--device-memory-limit"))
	if pool != maximum || spill >= maximum {
		t.Fatalf("pool %v, maximum %v, spill %v", pool, maximum, spill)
	}
	if flagValue(t, args, "--set-rmm-allocator-for-libs") != "cupy" {
		t.Fatal("CuPy does not allocate from the RMM pool")
	}
	if float64(replicas)*maximum > a10Bytes-headroomBytes {
		t.Fatalf("%d pools of %.1f GiB do not fit an A10-24Q with headroom", replicas, maximum/gib)
	}

	job := readDocuments(t, filepath.Join(root, "config", "dask", "sample", "job.yaml"))[0]
	for _, env := range dig(job, "spec", "template", "spec", "containers", 0, "env").([]any) {
		if dig(env, "name") == "EXPECTED_WORKERS" && dig(env, "value") != strconv.Itoa(replicas) {
			t.Fatalf("sample job expects %v workers, deployment has %d", dig(env, "value"), replicas)
		}
	}
}

func TestDaskPodsShareImageOnGPUNode(t *testing.T) {
	root := repoRoot(t)
	pods := []any{
		dig(readDocuments(t, filepath.Join(root, "config", "dask", "workers.yaml"))[0], "spec", "template", "spec"),
		dig(readDocuments(t, filepath.Join(root, "config", "dask", "scheduler.yaml"))[0], "spec", "template", "spec"),
		dig(readDocuments(t, filepath.Join(root, "config", "dask", "sample", "job.yaml"))[0], "spec", "template", "spec"),
	}
	images := map[any]bool{}
	for _, pod := range pods {
		container := dig(pod, "containers", 0).(map[string]any)
		images[container["image"]] = true
		// Keep the image entrypoint, which sets up the conda environment
		if _, ok := container["command"]; ok {
			t.Error("a Dask container overrides the image entrypoint")
		}
		if dig(pod, "nodeSelector", "nvidia.com/gpu.present") != "true" {
			t.Error("a Dask pod is not pinned to the GPU node")
		}
	}
	if len(images) != 1 {
		t.Fatalf("Dask pods use %d images, want 1", len(images))
	}
}
