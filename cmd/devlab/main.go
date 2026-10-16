// Command devlab manages the dev-lab kind cluster.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/jbotstevens/dev-lab/internal/cli"
)

// version is set at build time: -ldflags "-X main.version=1.2.3"
var version = "dev"

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	err := cli.NewRootCommand(version, os.Stdout).ExecuteContext(ctx)
	var exitErr cli.ExitError
	switch {
	case errors.As(err, &exitErr):
		os.Exit(exitErr.Code)
	case err != nil:
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(1)
	}
}
