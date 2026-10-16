package lab

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
)

// Cmd is one external command: a bundled CLI, docker or nvidia-smi.
type Cmd struct {
	Name  string
	Args  []string
	Env   []string // added to the current environment
	Stdin io.Reader
}

func (c Cmd) String() string {
	return strings.Join(append([]string{c.Name}, c.Args...), " ")
}

// Runner runs external commands. Tests replace it with a fake.
type Runner interface {
	// Run streams the command's output to the console.
	Run(ctx context.Context, cmd Cmd) error
	// Output returns stdout; on failure the error includes stderr.
	Output(ctx context.Context, cmd Cmd) (string, error)
}

// ExecRunner runs commands with os/exec.
type ExecRunner struct {
	Stdout io.Writer
	Stderr io.Writer
}

func (r ExecRunner) command(ctx context.Context, cmd Cmd) *exec.Cmd {
	command := exec.CommandContext(ctx, cmd.Name, cmd.Args...)
	command.Env = append(os.Environ(), cmd.Env...)
	command.Stdin = cmd.Stdin
	return command
}

func (r ExecRunner) Run(ctx context.Context, cmd Cmd) error {
	command := r.command(ctx, cmd)
	command.Stdout = r.Stdout
	command.Stderr = r.Stderr
	if err := command.Run(); err != nil {
		return fmt.Errorf("%s: %w", cmd.Name, err)
	}
	return nil
}

func (r ExecRunner) Output(ctx context.Context, cmd Cmd) (string, error) {
	command := r.command(ctx, cmd)
	var stdout, stderr bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = &stderr
	if err := command.Run(); err != nil {
		message := strings.TrimSpace(stderr.String())
		if message == "" {
			return stdout.String(), fmt.Errorf("%s: %w", cmd.Name, err)
		}
		return stdout.String(), fmt.Errorf("%s: %w: %s", cmd.Name, err, message)
	}
	return stdout.String(), nil
}
