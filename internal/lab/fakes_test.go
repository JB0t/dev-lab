package lab

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// fakeRunner records commands and answers them with respond.
type fakeRunner struct {
	commands []Cmd
	stdin    []string
	respond  func(cmd Cmd) (string, error)
}

func (r *fakeRunner) record(cmd Cmd) (string, error) {
	r.commands = append(r.commands, cmd)
	input := ""
	if cmd.Stdin != nil {
		data, _ := io.ReadAll(cmd.Stdin)
		input = string(data)
	}
	r.stdin = append(r.stdin, input)
	if r.respond == nil {
		return "", nil
	}
	return r.respond(cmd)
}

func (r *fakeRunner) Run(_ context.Context, cmd Cmd) error {
	_, err := r.record(cmd)
	return err
}

func (r *fakeRunner) Output(_ context.Context, cmd Cmd) (string, error) {
	return r.record(cmd)
}

// lines returns each recorded command as "<tool basename> <args>".
func (r *fakeRunner) lines() []string {
	var result []string
	for _, cmd := range r.commands {
		result = append(result, strings.Join(append([]string{filepath.Base(cmd.Name)}, cmd.Args...), " "))
	}
	return result
}

func (r *fakeRunner) find(substring string) (int, bool) {
	for i, line := range r.lines() {
		if strings.Contains(line, substring) {
			return i, true
		}
	}
	return -1, false
}

type fakeNode struct {
	name     string
	scripts  []string
	params   string
	archives int
}

func (n *fakeNode) Name() string { return n.name }

func (n *fakeNode) Exec(_ io.Reader, stdout, _ io.Writer, name string, args ...string) error {
	if name == "cat" {
		if n.params == "" {
			return fmt.Errorf("no such file")
		}
		fmt.Fprint(stdout, n.params)
		return nil
	}
	n.scripts = append(n.scripts, args[len(args)-1])
	return nil
}

func (n *fakeNode) LoadImageArchive(io.Reader) error {
	n.archives++
	return nil
}

type fakeCluster struct {
	exists  bool
	created []byte
	deleted bool
	nodes   []*fakeNode
}

func (c *fakeCluster) Exists(string) (bool, error) { return c.exists, nil }

func (c *fakeCluster) Create(_ string, config []byte, _ string, _ time.Duration) error {
	c.created = config
	c.exists = true
	return nil
}

func (c *fakeCluster) Delete(string, string) error {
	c.deleted = true
	c.exists = false
	return nil
}

func (c *fakeCluster) Nodes(string) ([]Node, error) {
	result := make([]Node, 0, len(c.nodes))
	for _, node := range c.nodes {
		result = append(result, node)
	}
	return result, nil
}

// repoRoot is the checkout this test runs in (a dev-lab home).
func repoRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	if !isHome(root) {
		t.Fatalf("%s is not a dev-lab home", root)
	}
	return root
}

// testLab returns a Lab on the repository with fake runner and cluster.
func testLab(t *testing.T) (*Lab, *fakeRunner, *fakeCluster, *bytes.Buffer) {
	t.Helper()
	var out bytes.Buffer
	runner := &fakeRunner{}
	cluster := &fakeCluster{}
	l := &Lab{
		Home:        Home{Root: repoRoot(t)},
		Run:         runner,
		Cluster:     cluster,
		Log:         &Logger{Out: &out},
		In:          strings.NewReader(""),
		RegistryDir: filepath.Join(t.TempDir(), "registry"),
		GOOS:        "linux",
		LookPath:    func(name string) (string, error) { return "/usr/bin/" + name, nil },
		Sleep:       func(time.Duration) {},
		HostKeys: func(context.Context, string) ([]string, error) {
			return []string{"github.com ssh-ed25519 AAAAtest"}, nil
		},
	}
	return l, runner, cluster, &out
}

// tempHome copies the files a test needs into a scratch dev-lab home.
func tempHome(t *testing.T, files map[string]string) Home {
	t.Helper()
	root := t.TempDir()
	files[homeMarker] = "kind: Cluster\n"
	for name, content := range files {
		path := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return Home{Root: root}
}
