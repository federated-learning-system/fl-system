package main

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/reflection"

	minioclient "github.com/x9z0/fls/aggregation-server/internal/minio"
	"github.com/x9z0/fls/aggregation-server/internal/service"
	"github.com/x9z0/fls/aggregation-server/internal/store"
	pb "github.com/x9z0/fls/proto"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	// ── Config ──────────────────────────────────────────────────────
	grpcPort := envOr("GRPC_PORT", "50051")
	metricsPort := envOr("METRICS_PORT", "9100")
	redisAddr := envOr("REDIS_ADDR", "localhost:6379")
	minioEndpoint := envOr("MINIO_ENDPOINT", "localhost:9000")
	minioAccessKey := envOr("MINIO_ACCESS_KEY", "flminio")
	minioSecretKey := envOr("MINIO_SECRET_KEY", "flminio123")
	minioSSL := envOr("MINIO_USE_SSL", "false") == "true"
	// MINIO_PRESIGN_ENDPOINT: when set, presigned URLs use this endpoint instead of the
	// internal one. Required for Docker/external clients that can't resolve minio:9000.
	minioPresignEndpoint := os.Getenv("MINIO_PRESIGN_ENDPOINT")

	tlsCert := envOr("TLS_CERT", "infra/certs/server.crt")
	tlsKey := envOr("TLS_KEY", "infra/certs/server.key")
	tlsCA := envOr("TLS_CA", "infra/certs/ca.crt")
	tlsEnabled := envOr("TLS_ENABLED", "true")

	registryURL := envOr("REGISTRY_URL", "http://client-registry:8081")
	inferenceURL := envOr("INFERENCE_URL", "http://inference-server:8000")

	// ── Redis ───────────────────────────────────────────────────────
	redisStore, err := store.New(redisAddr, log)
	if err != nil {
		log.Error("redis connection failed", "error", err)
		os.Exit(1)
	}
	defer redisStore.Close()
	log.Info("connected to Redis", "addr", redisAddr)

	// ── MinIO ───────────────────────────────────────────────────────
	mc, err := minioclient.New(minioEndpoint, minioAccessKey, minioSecretKey, minioSSL, log, minioPresignEndpoint)
	if err != nil {
		log.Error("minio connection failed", "error", err)
		os.Exit(1)
	}
	log.Info("connected to MinIO", "endpoint", minioEndpoint)

	// ── gRPC Server ─────────────────────────────────────────────────
	var grpcOpts []grpc.ServerOption

	if tlsEnabled == "true" {
		tlsConfig, err := loadMTLS(tlsCert, tlsKey, tlsCA)
		if err != nil {
			log.Error("mTLS setup failed", "error", err)
			os.Exit(1)
		}
		grpcOpts = append(grpcOpts, grpc.Creds(credentials.NewTLS(tlsConfig)))
		log.Info("mTLS enabled",
			"cert", tlsCert,
			"key", tlsKey,
			"ca", tlsCA,
		)
	} else {
		log.Warn("mTLS DISABLED — insecure mode")
	}

	// Max message size: 64MB for model deltas
	grpcOpts = append(grpcOpts, grpc.MaxRecvMsgSize(64*1024*1024))
	grpcOpts = append(grpcOpts, grpc.MaxSendMsgSize(64*1024*1024))

	grpcServer := grpc.NewServer(grpcOpts...)

	svc := service.NewAggregationServer(redisStore, mc, service.Config{
		RegistryURL:  registryURL,
		InferenceURL: inferenceURL,
	}, log)
	pb.RegisterAggregationServiceServer(grpcServer, svc)
	reflection.Register(grpcServer)

	// ── Prometheus metrics endpoint ─────────────────────────────────
	go func() {
		mux := http.NewServeMux()
		mux.Handle("/metrics", promhttp.Handler())
		mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
			if err := redisStore.Ping(r.Context()); err != nil {
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

	// ── Listen ──────────────────────────────────────────────────────
	lis, err := net.Listen("tcp", ":"+grpcPort)
	if err != nil {
		log.Error("listen failed", "error", err)
		os.Exit(1)
	}

	// Graceful shutdown
	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Info("aggregation-server listening", "port", grpcPort, "tls", tlsEnabled)
		if err := grpcServer.Serve(lis); err != nil {
			log.Error("gRPC server error", "error", err)
			os.Exit(1)
		}
	}()

	<-done
	log.Info("shutting down...")
	grpcServer.GracefulStop()
	log.Info("server stopped")
}

// loadMTLS loads server cert/key and CA cert for mutual TLS.
func loadMTLS(certFile, keyFile, caFile string) (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("load server cert: %w", err)
	}

	caCert, err := os.ReadFile(caFile)
	if err != nil {
		return nil, fmt.Errorf("read CA cert: %w", err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caCert) {
		return nil, fmt.Errorf("failed to parse CA cert")
	}

	return &tls.Config{
		Certificates: []tls.Certificate{cert},
		ClientAuth:   tls.RequireAndVerifyClientCert,
		ClientCAs:    caPool,
		MinVersion:   tls.VersionTLS12,
	}, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
