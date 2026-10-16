package lab

import (
	"fmt"
	"io"
)

// Logger prints progress in the style of the old Python CLI: a coloured
// line per step, with ✅ on success.
type Logger struct {
	Out   io.Writer
	Color bool
}

const (
	colorReset  = "\033[0m"
	colorRed    = "\033[0;31m"
	colorGreen  = "\033[0;32m"
	colorYellow = "\033[1;33m"
	colorBlue   = "\033[0;34m"
	colorCyan   = "\033[0;36m"
	colorBold   = "\033[1m"
)

func (l *Logger) print(color, format string, args ...any) {
	message := fmt.Sprintf(format, args...)
	if l.Color {
		fmt.Fprintf(l.Out, "%s%s%s\n", color, message, colorReset)
		return
	}
	fmt.Fprintln(l.Out, message)
}

// Section starts a group of steps.
func (l *Logger) Section(format string, args ...any) {
	fmt.Fprintln(l.Out)
	l.print(colorBold+colorBlue, format, args...)
}

func (l *Logger) Step(format string, args ...any) { l.print(colorBlue, format, args...) }
func (l *Logger) OK(format string, args ...any)   { l.print(colorGreen, "✅ "+format, args...) }
func (l *Logger) Warn(format string, args ...any) { l.print(colorYellow, format, args...) }
func (l *Logger) Fail(format string, args ...any) { l.print(colorRed, format, args...) }
func (l *Logger) Info(format string, args ...any) { l.print(colorCyan, format, args...) }

// Plain prints without colour, e.g. command output or a table.
func (l *Logger) Plain(format string, args ...any) { fmt.Fprintf(l.Out, format+"\n", args...) }
