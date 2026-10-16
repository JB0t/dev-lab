// Package cli is the devlab command line.
package cli

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"

	"github.com/spf13/cobra"
	"golang.org/x/term"

	"github.com/jbotstevens/dev-lab/internal/lab"
)

// ExitError carries a passthrough tool's exit code back to main.
type ExitError struct{ Code int }

func (e ExitError) Error() string { return fmt.Sprintf("exit status %d", e.Code) }

type app struct {
	home    string
	noColor bool
	out     io.Writer
	lab     *lab.Lab
}

// load finds the dev-lab home and builds the Lab.
func (a *app) load() (*lab.Lab, error) {
	if a.lab != nil {
		return a.lab, nil
	}
	explicit := a.home
	if explicit == "" {
		explicit = os.Getenv("DEVLAB_HOME")
	}
	executable, _ := os.Executable()
	workingDir, _ := os.Getwd()
	home, err := lab.FindHome(explicit, executable, workingDir)
	if err != nil {
		return nil, err
	}
	color := !a.noColor && os.Getenv("NO_COLOR") == "" && isTerminal(os.Stdout)
	a.lab = lab.New(home, a.out, color, isTerminal(os.Stdin))
	return a.lab, nil
}

func isTerminal(file *os.File) bool {
	return term.IsTerminal(int(file.Fd()))
}

// NewRootCommand builds the devlab command tree.
func NewRootCommand(version string, out io.Writer) *cobra.Command {
	a := &app{out: out}
	root := &cobra.Command{
		Use:   "devlab",
		Short: "Local Kubernetes development lab on kind",
		Long: `devlab creates and manages the dev-lab kind cluster: Linkerd service mesh,
local registry, monitoring, GitOps with Flux, and optional NVIDIA GPUs.

It runs from a dev-lab home: an unpacked release (bin/devlab plus cluster/
and config/) or a checkout of the repository. Docker is the only host
requirement; kubectl, helm, linkerd and flux are bundled in bin/.`,
		Version:       version,
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.SetOut(out)
	root.PersistentFlags().StringVar(&a.home, "home", "", "dev-lab home directory (default: next to the binary, or DEVLAB_HOME)")
	root.PersistentFlags().BoolVar(&a.noColor, "no-color", false, "disable coloured output")

	root.AddCommand(
		a.bootstrapCommand(),
		a.deployTraditionalCommand("deploy-traditional", "Deploy registry, metrics-server, ingress and monitoring"),
		a.deployTraditionalCommand("deploy", "Deploy using the traditional method (alias of deploy-traditional)"),
		a.deployGitOpsCommand(),
		a.statusCommand(),
		a.testCommand(),
		a.cleanupCommand(),
		a.gpuPluginCommand(),
		a.loadImageCommand(),
		a.kubeconfigCommand(),
	)
	for _, tool := range []string{"kubectl", "helm", "linkerd", "flux"} {
		root.AddCommand(a.toolCommand(tool))
	}
	return root
}

func (a *app) bootstrapCommand() *cobra.Command {
	var opts lab.BootstrapOptions
	cmd := &cobra.Command{
		Use:   "bootstrap",
		Short: "Create the dev-lab cluster and install Linkerd",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.Bootstrap(cmd.Context(), opts)
		},
	}
	cmd.Flags().BoolVar(&opts.GPU, "gpu", false, "create a GPU-enabled cluster (Linux host with NVIDIA GPU, see README)")
	cmd.Flags().BoolVar(&opts.Recreate, "recreate", false, "delete an existing dev-lab cluster without asking")
	return cmd
}

func (a *app) deployTraditionalCommand(use, short string) *cobra.Command {
	return &cobra.Command{
		Use:   use,
		Short: short,
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.DeployTraditional(cmd.Context())
		},
	}
}

func (a *app) deployGitOpsCommand() *cobra.Command {
	var opts lab.GitOpsOptions
	cmd := &cobra.Command{
		Use:   "deploy-gitops",
		Short: "Install Flux and deploy infrastructure and apps from Git",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.DeployGitOps(cmd.Context(), opts)
		},
	}
	cmd.Flags().StringVar(&opts.RepoURL, "repo-url", "", "Git repository URL (default: the url in config/gitops/git-repository.yaml)")
	cmd.Flags().BoolVar(&opts.NoPrompt, "no-prompt", false, "do not wait for the deploy key to be added")
	return cmd
}

func (a *app) statusCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Show cluster and node status",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.Status(cmd.Context())
		},
	}
}

func (a *app) testCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "test",
		Short: "Test a deployed environment end to end",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.Test(cmd.Context())
		},
	}
}

func (a *app) cleanupCommand() *cobra.Command {
	var yes bool
	cmd := &cobra.Command{
		Use:   "cleanup",
		Short: "Delete the dev-lab cluster",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.Cleanup(cmd.Context(), yes)
		},
	}
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "do not ask for confirmation")
	return cmd
}

func (a *app) gpuPluginCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "gpu-plugin",
		Short: "Install or update the NVIDIA device plugin (applies time-slicing changes)",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.SetupGPUDevicePlugin(cmd.Context())
		},
	}
}

func (a *app) loadImageCommand() *cobra.Command {
	var nodes []string
	cmd := &cobra.Command{
		Use:   "load-image IMAGE...",
		Short: "Load local Docker images into the cluster nodes (replaces kind load docker-image)",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, images []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			return l.LoadImages(cmd.Context(), images, nodes)
		},
	}
	cmd.Flags().StringSliceVar(&nodes, "nodes", nil, "only these nodes, e.g. dev-lab-worker (default: all)")
	return cmd
}

func (a *app) kubeconfigCommand() *cobra.Command {
	return &cobra.Command{
		Use:   "kubeconfig",
		Short: "Print the path of the dev-lab kubeconfig",
		Long:  "Print the path of the dev-lab kubeconfig, e.g. export KUBECONFIG=$(bin/devlab kubeconfig)",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			l, err := a.load()
			if err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), l.Home.Kubeconfig())
			return nil
		},
	}
}

// toolCommand passes its arguments to a bundled CLI, with KUBECONFIG set to
// the dev-lab kubeconfig. A leading "--" is optional.
func (a *app) toolCommand(tool string) *cobra.Command {
	return &cobra.Command{
		Use:                tool + " [args...]",
		Short:              fmt.Sprintf("Run the bundled %s against the dev-lab cluster", tool),
		DisableFlagParsing: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) > 0 && args[0] == "--" {
				args = args[1:]
			}
			l, err := a.load()
			if err != nil {
				return err
			}
			return runTool(cmd.Context(), l.ToolCmd(tool, args...))
		},
	}
}

func runTool(ctx context.Context, tool lab.Cmd) error {
	command := exec.CommandContext(ctx, tool.Name, tool.Args...)
	command.Env = append(os.Environ(), tool.Env...)
	command.Stdin, command.Stdout, command.Stderr = os.Stdin, os.Stdout, os.Stderr
	err := command.Run()
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return ExitError{Code: exitErr.ExitCode()}
	}
	if err != nil && strings.Contains(err.Error(), "executable file not found") {
		return fmt.Errorf("%s not found: it is bundled in release tarballs; in a checkout run scripts/fetch-tools.sh", tool.Name)
	}
	return err
}
