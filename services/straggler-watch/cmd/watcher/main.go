package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"

	"github.com/x9z0/fls/straggler-watch/internal/watch"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	// ── Config ──────────────────────────────────────────────────────
	redisAddr := envOr("REDIS_ADDR", "localhost:6379")
	metricsPort := envOr("METRICS_PORT", "9100")

	// ── Redis ───────────────────────────────────────────────────────
	rdb := redis.NewClient(&redis.Options{
		Addr:         redisAddr,
		DB:           0,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 5 * time.Second,
		PoolSize:     10,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Error("redis connection failed", "error", err)
		os.Exit(1)
	}
	cancel()
	defer rdb.Close()
	log.Info("connected to Redis", "addr", redisAddr)

	// ── Prometheus metrics endpoint ─────────────────────────────────
	go func() {
		mux := http.NewServeMux()
		mux.Handle("/metrics", promhttp.Handler())
		mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
			if err := rdb.Ping(r.Context()).Err(); err != nil {
				http.Error(w, "redis unhealthy", http.StatusServiceUnavailable)
				return
			}
			w.WriteHeader(http.StatusOK)
			w.Write([]byte("ok"))
		})
		log.Info("metrics server listening", "port", metricsPort)
		if err := http.ListenAndServe(":"+metricsPort, mux); err != nil {
			log.Error("metrics server error", "error", err)
		}
	}()

	// ── Watcher ─────────────────────────────────────────────────────
	watcher := watch.New(rdb, log)

	// Graceful shutdown
	runCtx, runCancel := context.WithCancel(context.Background())
	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-done
		log.Info("shutting down...")
		runCancel()
	}()

	log.Info("straggler-watch starting")
	if err := watcher.Run(runCtx); err != nil && err != context.Canceled {
		log.Error("watcher error", "error", err)
		os.Exit(1)
	}
	log.Info("straggler-watch stopped")
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
