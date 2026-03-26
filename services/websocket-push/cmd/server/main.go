package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/x9z0/fls/websocket-push/internal/handler"
	"github.com/x9z0/fls/websocket-push/internal/hub"
	"github.com/x9z0/fls/websocket-push/internal/redissub"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	// ── Config ──────────────────────────────────────────────────────
	port := envOr("PORT", "8080")
	redisAddr := envOr("REDIS_ADDR", "localhost:6379")

	// ── Redis ───────────────────────────────────────────────────────
	rdb := redis.NewClient(&redis.Options{
		Addr:         redisAddr,
		DB:           0,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  0, // no timeout for pub/sub blocking reads
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

	// ── Hub ─────────────────────────────────────────────────────────
	h := hub.New(log)
	go h.Run()

	// ── Redis subscriber ────────────────────────────────────────────
	sub := redissub.New(rdb, h, log)

	runCtx, runCancel := context.WithCancel(context.Background())
	go func() {
		if err := sub.Run(runCtx); err != nil && err != context.Canceled {
			log.Error("subscriber error", "error", err)
		}
	}()

	// ── HTTP + WebSocket server ─────────────────────────────────────
	wsHandler := &handler.Handler{Hub: h, Log: log}

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", wsHandler.ServeWS)
	mux.HandleFunc("/connections", wsHandler.Connections)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if err := rdb.Ping(r.Context()).Err(); err != nil {
			http.Error(w, "unhealthy", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	})

	srv := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	// ── Graceful shutdown ───────────────────────────────────────────
	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Info("websocket-push listening", "port", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	<-done
	log.Info("shutting down...")
	runCancel()

	shutCtx, shutCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutCancel()
	srv.Shutdown(shutCtx)
	log.Info("websocket-push stopped")
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
