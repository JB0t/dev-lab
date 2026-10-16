package lab

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// homeMarker identifies a dev-lab home: an unpacked release tarball or a
// checkout of the repository (both have the same layout).
const homeMarker = "cluster/kind-config.yaml"

// Home is the directory that holds bin/, cluster/, config/ and the
// generated .kube/config for one dev-lab installation.
type Home struct {
	Root string
}

// FindHome locates the dev-lab home, in order: the explicit directory
// (--home or DEVLAB_HOME), the directory above the running binary
// (<home>/bin/devlab), then the working directory and its parents.
func FindHome(explicit, executable, workingDir string) (Home, error) {
	if explicit != "" {
		if !isHome(explicit) {
			return Home{}, fmt.Errorf("%s is not a dev-lab home (no %s)", explicit, homeMarker)
		}
		return newHome(explicit)
	}
	if executable != "" {
		if resolved, err := filepath.EvalSymlinks(executable); err == nil {
			executable = resolved
		}
		if root := filepath.Dir(filepath.Dir(executable)); isHome(root) {
			return newHome(root)
		}
	}
	for dir := workingDir; dir != ""; dir = parentDir(dir) {
		if isHome(dir) {
			return newHome(dir)
		}
	}
	return Home{}, fmt.Errorf("no dev-lab home found: run bin/devlab from an unpacked release, "+
		"or set --home / DEVLAB_HOME to a directory containing %s", homeMarker)
}

func isHome(dir string) bool {
	info, err := os.Stat(filepath.Join(dir, homeMarker))
	return err == nil && !info.IsDir()
}

func parentDir(dir string) string {
	parent := filepath.Dir(dir)
	if parent == dir {
		return ""
	}
	return parent
}

func newHome(dir string) (Home, error) {
	root, err := filepath.Abs(dir)
	if err != nil {
		return Home{}, err
	}
	return Home{Root: root}, nil
}

// Path joins elements onto the home directory.
func (h Home) Path(elem ...string) string {
	return filepath.Join(append([]string{h.Root}, elem...)...)
}

// Kubeconfig is the kubeconfig dev-lab writes for the cluster. It is kept
// inside the home so dev-lab never edits ~/.kube/config.
func (h Home) Kubeconfig() string {
	return h.Path(".kube", "config")
}

// Tool returns the path of a bundled CLI (bin/<name>), falling back to the
// one on PATH, e.g. in a checkout where the tools were not fetched.
func (h Home) Tool(name string) string {
	bundled := h.Path("bin", name)
	if info, err := os.Stat(bundled); err == nil && !info.IsDir() && info.Mode()&0o111 != 0 {
		return bundled
	}
	if onPath, err := exec.LookPath(name); err == nil {
		return onPath
	}
	return bundled
}
