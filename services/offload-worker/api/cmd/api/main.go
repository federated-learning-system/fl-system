package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	miniogo "github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/redis/go-redis/v9"

	"github.com/x9z0/fls/offload-api/internal/handler"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	// ── Config ──────────────────────────────────────────────────────
	port := envOr("PORT", "8085")
	redisAddr := envOr("REDIS_ADDR", "localhost:6379")
	minioEndpoint := envOr("MINIO_ENDPOINT", "localhost:9000")
	minioAccessKey := envOr("MINIO_ACCESS_KEY", "flminio")
	minioSecretKey := envOr("MINIO_SECRET_KEY", "flminio123")
	minioUseSSL := envOr("MINIO_USE_SSL", "false") == "true"

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

	// ── MinIO ───────────────────────────────────────────────────────
	mc, err := miniogo.New(minioEndpoint, &miniogo.Options{
		Creds:  credentials.NewStaticV4(minioAccessKey, minioSecretKey, ""),
		Secure: minioUseSSL,
	})
	if err != nil {
		log.Error("minio client failed", "error", err)
		os.Exit(1)
	}

	// Ensure fl-offload bucket exists
	bucketCtx, bucketCancel := context.WithTimeout(context.Background(), 10*time.Second)
	exists, err := mc.BucketExists(bucketCtx, "fl-offload")
	if err != nil {
		log.Warn("bucket check failed", "error", err)
	} else if !exists {
		if err := mc.MakeBucket(bucketCtx, "fl-offload", miniogo.MakeBucketOptions{}); err != nil {
			log.Warn("bucket creation failed (may already exist)", "error", err)
		} else {
			log.Info("created bucket fl-offload")
		}
	}
	bucketCancel()
	log.Info("connected to MinIO", "endpoint", minioEndpoint)

	// ── Handler ─────────────────────────────────────────────────────
	h := handler.New(rdb, mc, log)
	h.EnsureStream(context.Background())

	// ── Router ──────────────────────────────────────────────────────
	r := chi.NewRouter()
	r.Use(middleware.Recoverer)
	r.Use(middleware.RealIP)

	r.Post("/offload/jobs", h.CreateJob)
	r.Get("/offload/jobs/{id}", h.GetJobStatus)
	r.Get("/healthz", h.Healthz)
	r.Get("/health", h.Healthz)

	// ── Server ──────────────────────────────────────────────────────
	srv := &http.Server{
		Addr:    ":" + port,
		Handler: r,
	}

	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Info("offload-api listening", "port", port)
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
	log.Info("offload-api stopped")
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
