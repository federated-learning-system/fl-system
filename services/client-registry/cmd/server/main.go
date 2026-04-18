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
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/x9z0/fls/client-registry/internal/auth"
	"github.com/x9z0/fls/client-registry/internal/handler"
	_ "github.com/x9z0/fls/client-registry/internal/metrics" // register metrics
	"github.com/x9z0/fls/client-registry/internal/store"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	// ── Config from env ─────────────────────────────────────────────
	port := envOr("PORT", "8081")
	metricsPort := envOr("METRICS_PORT", "9100")
	dbHost := envOr("DB_HOST", "localhost")
	dbPort := envOr("DB_PORT", "5432")
	dbUser := envOr("DB_USER", "postgres")
	dbPass := envOr("DB_PASSWORD", "flpg123")
	dbName := envOr("DB_NAME", "fl_registry")
	jwtSecret := envOr("JWT_SECRET", "fl-dev-secret-change-in-prod")

	dsn := fmt.Sprintf("postgres://%s:%s@%s:%s/%s?sslmode=disable",
		dbUser, dbPass, dbHost, dbPort, dbName)

	// ── Database ────────────────────────────────────────────────────
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	pool, err := store.ConnectPool(ctx, dsn)
	if err != nil {
		log.Error("database connection failed", "error", err)
		os.Exit(1)
	}
	defer pool.Close()
	log.Info("connected to PostgreSQL", "host", dbHost, "db", dbName)

	s := store.New(pool)
	j := auth.New(jwtSecret, 15*time.Minute)
	h := handler.New(s, j, log)

	// ── Router ──────────────────────────────────────────────────────
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(30 * time.Second))

	// Public routes
	r.Get("/healthz", h.Healthz)
	r.Post("/clients/register", h.Register)
	r.Get("/clients/eligible", h.Eligible)
	r.Get("/clients/{id}", h.GetClient)

	// Authenticated routes
	r.Group(func(r chi.Router) {
		r.Use(j.Middleware)
		r.Put("/clients/{id}/heartbeat", h.Heartbeat)
		r.Post("/clients/{id}/budget", h.UpdateBudget)
		r.Post("/auth/refresh", h.RefreshToken)
	})

	// ── Prometheus metrics endpoint ─────────────────────────────────
	go func() {
		mux := http.NewServeMux()
		mux.Handle("/metrics", promhttp.Handler())
		mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
			w.Write([]byte("ok"))
		})
		log.Info("metrics server listening", "port", metricsPort)
		if err := http.ListenAndServe(":"+metricsPort, mux); err != nil {
			log.Error("metrics server error", "error", err)
		}
	}()

	// ── Server ──────────────────────────────────────────────────────
	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Graceful shutdown
	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Info("client-registry listening", "port", port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	<-done
	log.Info("shutting down...")

	shutCtx, shutCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutCancel()
	if err := srv.Shutdown(shutCtx); err != nil {
		log.Error("shutdown error", "error", err)
	}
	log.Info("server stopped")
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
