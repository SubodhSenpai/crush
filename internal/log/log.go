package log

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"runtime/debug"
	"sync"
	"sync/atomic"
	"time"

	"gopkg.in/natefinch/lumberjack.v2"
)

var (
	initOnce    sync.Once
	initialized atomic.Bool

	fileHandler slog.Handler
)

func Setup(logFile string, debug bool) {
	initOnce.Do(func() {
		logRotator := &lumberjack.Logger{
			Filename:   logFile,
			MaxSize:    10,    // Max size in MB
			MaxBackups: 0,     // Number of backups
			MaxAge:     30,    // Days
			Compress:   false, // Enable compression
		}

		level := slog.LevelInfo
		if debug {
			level = slog.LevelDebug
		}

		fileHandler = slog.NewJSONHandler(logRotator, &slog.HandlerOptions{
			Level:     level,
			AddSource: true,
		})

		slog.SetDefault(slog.New(fileHandler))
		initialized.Store(true)
	})
}

// EnableConsoleLogging adds a console (stdout) text handler in addition to the rotating file handler.
// Safe to call multiple times; it will rebuild the default logger with both handlers.
func EnableConsoleLogging(debug bool) {
	if !Initialized() {
		return
	}
	level := slog.LevelInfo
	if debug {
		level = slog.LevelDebug
	}
	console := slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: level, AddSource: true})
	var base slog.Handler = console
	if fileHandler != nil {
		base = newMultiHandler(fileHandler, console)
	}
	slog.SetDefault(slog.New(base))
}

// multiHandler forwards records to multiple handlers.
type multiHandler struct{ handlers []slog.Handler }

func newMultiHandler(h ...slog.Handler) slog.Handler { return &multiHandler{handlers: h} }

func (m *multiHandler) Enabled(ctx context.Context, level slog.Level) bool {
	for _, h := range m.handlers {
		if h.Enabled(ctx, level) {
			return true
		}
	}
	return false
}

func (m *multiHandler) Handle(ctx context.Context, r slog.Record) error {
	var firstErr error
	for _, h := range m.handlers {
		if err := h.Handle(ctx, r); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

func (m *multiHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	next := make([]slog.Handler, 0, len(m.handlers))
	for _, h := range m.handlers {
		next = append(next, h.WithAttrs(attrs))
	}
	return &multiHandler{handlers: next}
}

func (m *multiHandler) WithGroup(name string) slog.Handler {
	next := make([]slog.Handler, 0, len(m.handlers))
	for _, h := range m.handlers {
		next = append(next, h.WithGroup(name))
	}
	return &multiHandler{handlers: next}
}

func Initialized() bool {
	return initialized.Load()
}

func RecoverPanic(name string, cleanup func()) {
	if r := recover(); r != nil {
		// Create a timestamped panic log file
		timestamp := time.Now().Format("20060102-150405")
		filename := fmt.Sprintf("crush-panic-%s-%s.log", name, timestamp)

		file, err := os.Create(filename)
		if err == nil {
			defer file.Close()

			// Write panic information and stack trace
			fmt.Fprintf(file, "Panic in %s: %v\n\n", name, r)
			fmt.Fprintf(file, "Time: %s\n\n", time.Now().Format(time.RFC3339))
			fmt.Fprintf(file, "Stack Trace:\n%s\n", debug.Stack())

			// Execute cleanup function if provided
			if cleanup != nil {
				cleanup()
			}
		}
	}
}
