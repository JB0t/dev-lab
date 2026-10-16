package lab

import (
	"io"
	"slices"
	"time"

	"sigs.k8s.io/kind/pkg/cluster"
	"sigs.k8s.io/kind/pkg/cluster/nodes"
	"sigs.k8s.io/kind/pkg/cluster/nodeutils"
	kindcmd "sigs.k8s.io/kind/pkg/cmd"
)

// Node is one kind node container.
type Node interface {
	Name() string
	// Exec runs a command inside the node container.
	Exec(stdin io.Reader, stdout, stderr io.Writer, name string, args ...string) error
	// LoadImageArchive imports a `docker save` archive into the node's containerd.
	LoadImageArchive(archive io.Reader) error
}

// ClusterProvider creates and inspects kind clusters. The kind library is
// compiled into devlab, so no kind binary is needed.
type ClusterProvider interface {
	Exists(name string) (bool, error)
	Create(name string, config []byte, kubeconfig string, wait time.Duration) error
	Delete(name, kubeconfig string) error
	Nodes(name string) ([]Node, error)
}

// KindProvider is the ClusterProvider backed by the kind library and Docker.
type KindProvider struct {
	provider *cluster.Provider
}

func NewKindProvider() *KindProvider {
	return &KindProvider{provider: cluster.NewProvider(
		cluster.ProviderWithDocker(),
		cluster.ProviderWithLogger(kindcmd.NewLogger()),
	)}
}

func (p *KindProvider) Exists(name string) (bool, error) {
	clusters, err := p.provider.List()
	if err != nil {
		return false, err
	}
	return slices.Contains(clusters, name), nil
}

func (p *KindProvider) Create(name string, config []byte, kubeconfig string, wait time.Duration) error {
	return p.provider.Create(name,
		cluster.CreateWithRawConfig(config),
		cluster.CreateWithNodeImage(KindNodeImage),
		cluster.CreateWithKubeconfigPath(kubeconfig),
		cluster.CreateWithWaitForReady(wait),
		cluster.CreateWithDisplayUsage(false),
		cluster.CreateWithDisplaySalutation(false),
	)
}

func (p *KindProvider) Delete(name, kubeconfig string) error {
	return p.provider.Delete(name, kubeconfig)
}

func (p *KindProvider) Nodes(name string) ([]Node, error) {
	kindNodes, err := p.provider.ListNodes(name)
	if err != nil {
		return nil, err
	}
	result := make([]Node, 0, len(kindNodes))
	for _, node := range kindNodes {
		result = append(result, kindNode{node})
	}
	return result, nil
}

type kindNode struct {
	node nodes.Node
}

func (n kindNode) Name() string { return n.node.String() }

func (n kindNode) Exec(stdin io.Reader, stdout, stderr io.Writer, name string, args ...string) error {
	cmd := n.node.Command(name, args...)
	if stdin != nil {
		cmd.SetStdin(stdin)
	}
	if stdout != nil {
		cmd.SetStdout(stdout)
	}
	if stderr != nil {
		cmd.SetStderr(stderr)
	}
	return cmd.Run()
}

func (n kindNode) LoadImageArchive(archive io.Reader) error {
	return nodeutils.LoadImageArchive(n.node, archive)
}
