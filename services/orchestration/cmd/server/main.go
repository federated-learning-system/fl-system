package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"github.com/x9z0/fls/orchestration/internal/grpcclient"
	"github.com/x9z0/fls/orchestration/internal/handler"
	"github.com/x9z0/fls/orchestration/internal/scheduler"
	"github.com/x9z0/fls/orchestration/internal/store"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	// ── Config ──────────────────────────────────────────────────────
	port := envOr("PORT", "8082")
	dbHost := envOr("DB_HOST", "localhost")
	dbPort := envOr("DB_PORT", "5432")
	dbUser := envOr("DB_USER", "postgres")
	dbPassword := envOr("DB_PASSWORD", "flpg123")
	dbName := envOr("DB_NAME", "fl_registry")

	aggAddr := envOr("AGG_GRPC_ADDR", "localhost:50051")
	tlsEnabled := envOr("TLS_ENABLED", "true")
	tlsCert := envOr("TLS_CERT", "infra/certs/client-tech.crt")
	tlsKey := envOr("TLS_KEY", "infra/certs/client-tech.key")
	tlsCA := envOr("TLS_CA", "infra/certs/ca.crt")

	registryURL := envOr("REGISTRY_URL", "http://client-registry:8081")
	minClients := int32(2)
	if v := os.Getenv("MIN_CLIENTS_PER_ROUND"); v != "" {
		var mc int
		fmt.Sscanf(v, "%d", &mc)
		if mc > 0 {
			minClients = int32(mc)
		}
	}
	roundIntervalMin := envOr("ROUND_INTERVAL_MINUTES", "60")

	// ── PostgreSQL ──────────────────────────────────────────────────
	dsn := fmt.Sprintf("postgres://%s:%s@%s:%s/%s?sslmode=disable",
		dbUser, dbPassword, dbHost, dbPort, dbName)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	pool, err := store.ConnectPool(ctx, dsn)
	cancel()
	if err != nil {
		log.Error("postgres connection failed", "error", err)
		os.Exit(1)
	}
	defer pool.Close()
	log.Info("connected to PostgreSQL", "host", dbHost, "db", dbName)

	pgStore := store.New(pool)

	// ── gRPC client to aggregation-server ───────────────────────────
	aggClient, err := grpcclient.New(grpcclient.Config{
		Addr:       aggAddr,
		TLSEnabled: tlsEnabled == "true",
		CertFile:   tlsCert,
		KeyFile:    tlsKey,
		CAFile:     tlsCA,
	}, log)
	if err != nil {
		log.Error("grpc client setup failed", "error", err)
		os.Exit(1)
	}
	defer aggClient.Close()
	log.Info("gRPC client connected", "addr", aggAddr, "tls", tlsEnabled)

	// ── Handler ────────────────────────────────────────────────────
	h := handler.New(pgStore, aggClient, handler.Config{
		RegistryURL: registryURL,
		MinClients:  minClients,
	}, log)

	// ── Cron scheduler ─────────────────────────────────────────────
	sched := scheduler.New(log)
	cronSpec := fmt.Sprintf("@every %sm", roundIntervalMin)
	if err := sched.Schedule(cronSpec, h.StartRoundCron); err != nil {
		log.Error("schedule cron failed", "error", err)
		os.Exit(1)
	}
	sched.Start()
	defer sched.Stop()

	// ── Chi router ─────────────────────────────────────────────────
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(30 * time.Second))

	r.Post("/rounds/start", h.StartRound)
	r.Post("/rounds/{id}/close", h.CloseRound)
	r.Get("/rounds/current", h.CurrentRound)
	r.Get("/rounds/history", h.History)
	r.Get("/healthz", h.Healthz)
	r.Get("/health", h.Healthz)

	// ── HTTP Server ────────────────────────────────────────────────
	srv := &http.Server{
		Addr:    ":" + port,
		Handler: r,
	}

	// Graceful shutdown
	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Info("orchestration server listening", "port", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	<-done
	log.Info("shutting down...")

	shutCtx, shutCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutCancel()
	srv.Shutdown(shutCtx)
	log.Info("server stopped")
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
