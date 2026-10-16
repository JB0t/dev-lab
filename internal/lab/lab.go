// Package lab implements the dev-lab operations behind the devlab CLI:
// creating the kind cluster (optionally GPU-enabled), installing Linkerd,
// the traditional and GitOps deployments, and the GPU device plugin.
package lab

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"runtime"
	"strings"
	"time"
)

const (
	ClusterName = "dev-lab"
	Context     = "kind-" + ClusterName

	// Must match the registry extraMount hostPath in cluster/kind-config.yaml
	// and cluster/nvkind-config-template.yaml.
	RegistryHostPath = "/tmp/dev-lab-registry"
)

// Pinned versions of everything bootstrap and deploy install. The bundled
// CLI versions are pinned in scripts/fetch-tools.sh.
const (
	// kind v0.20.0's default node image (Kubernetes v1.27.3)
	KindNodeImage = "kindest/node:v1.27.3@sha256:3966ac761ae0136263ffdb6cfd4db23ef8a83cba8a463690e98317add2c9ba72"

	GatewayAPIURL    = "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml"
	MetricsServerURL = "https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml"
	IngressNginxURL  = "https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/kind/deploy.yaml"

	PrometheusChartRepo = "https://prometheus-community.github.io/helm-charts"

	NvidiaDevicePluginVersion = "0.20.1"
	NvidiaDevicePluginRepo    = "https://nvidia.github.io/k8s-device-plugin"
)

// Lab runs dev-lab operations against one home directory.
type Lab struct {
	Home    Home
	Run     Runner
	Cluster ClusterProvider
	Log     *Logger
	In      io.Reader

	// Interactive is false when stdin is not a terminal; prompts then take
	// their default answer.
	Interactive bool

	// RegistryDir is created before the cluster (the registry's extraMount)
	RegistryDir string

	// Overridable in tests
	GOOS     string
	LookPath func(string) (string, error)
	Sleep    func(time.Duration)
	HostKeys func(ctx context.Context, host string) ([]string, error)
}

// New returns a Lab wired to the real system.
func New(home Home, out io.Writer, color, interactive bool) *Lab {
	return &Lab{
		Home:        home,
		Run:         ExecRunner{Stdout: out, Stderr: out},
		Cluster:     NewKindProvider(),
		Log:         &Logger{Out: out, Color: color},
		In:          os.Stdin,
		Interactive: interactive,
		RegistryDir: RegistryHostPath,
		GOOS:        runtime.GOOS,
		LookPath:    lookPath,
		Sleep:       time.Sleep,
		HostKeys:    ScanHostKeys,
	}
}

// ToolCmd builds a command for a bundled CLI, pointed at the dev-lab
// kubeconfig. kubectl, helm, linkerd and flux all honour KUBECONFIG.
func (l *Lab) ToolCmd(name string, args ...string) Cmd {
	return Cmd{
		Name: l.Home.Tool(name),
		Args: args,
		Env:  []string{"KUBECONFIG=" + l.Home.Kubeconfig()},
	}
}

func (l *Lab) kubectlCmd(args ...string) Cmd {
	return l.ToolCmd("kubectl", append([]string{"--context", Context}, args...)...)
}

// kubectl runs kubectl against the dev-lab cluster, streaming its output.
func (l *Lab) kubectl(ctx context.Context, args ...string) error {
	return l.Run.Run(ctx, l.kubectlCmd(args...))
}

// kubectlOutput runs kubectl and returns its stdout.
func (l *Lab) kubectlOutput(ctx context.Context, args ...string) (string, error) {
	return l.Run.Output(ctx, l.kubectlCmd(args...))
}

// applyManifest pipes YAML into kubectl apply.
func (l *Lab) applyManifest(ctx context.Context, manifest string) error {
	cmd := l.kubectlCmd("apply", "-f", "-")
	cmd.Stdin = strings.NewReader(manifest)
	return l.Run.Run(ctx, cmd)
}

// applyFile applies a manifest file or URL.
func (l *Lab) applyFile(ctx context.Context, path string) error {
	return l.kubectl(ctx, "apply", "-f", path)
}

func (l *Lab) helm(ctx context.Context, args ...string) error {
	return l.Run.Run(ctx, l.ToolCmd("helm", append(args, "--kube-context", Context)...))
}

// confirm asks a yes/no question; the default is no.
func (l *Lab) confirm(question string) bool {
	if !l.Interactive {
		l.Log.Warn("%s [y/N]: no (not a terminal)", question)
		return false
	}
	fmt.Fprintf(l.Log.Out, "%s [y/N]: ", question)
	answer, _ := bufio.NewReader(l.In).ReadString('\n')
	answer = strings.ToLower(strings.TrimSpace(answer))
	return answer == "y" || answer == "yes"
}

// CheckDocker fails unless the Docker daemon is reachable.
func (l *Lab) CheckDocker(ctx context.Context) error {
	if _, err := l.Run.Output(ctx, Cmd{Name: "docker", Args: []string{"info", "--format", "{{.ServerVersion}}"}}); err != nil {
		return fmt.Errorf("docker is not available: %w", err)
	}
	return nil
}

// clusterReachable reports whether the API server answers.
func (l *Lab) clusterReachable(ctx context.Context) bool {
	_, err := l.kubectlOutput(ctx, "cluster-info")
	return err == nil
}
