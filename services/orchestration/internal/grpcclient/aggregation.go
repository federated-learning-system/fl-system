package grpcclient

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log/slog"
	"os"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"

	pb "github.com/x9z0/fls/proto"
)

// AggregationClient wraps the gRPC stub for AggregationService.
type AggregationClient struct {
	conn   *grpc.ClientConn
	stub   pb.AggregationServiceClient
	log    *slog.Logger
}

// Config holds gRPC client connection settings.
type Config struct {
	Addr       string // e.g. "aggregation-server:50051"
	TLSEnabled bool
	CertFile   string // client cert
	KeyFile    string // client key
	CAFile     string // CA cert
}

// New creates a gRPC client connection to the aggregation server.
func New(cfg Config, log *slog.Logger) (*AggregationClient, error) {
	var opts []grpc.DialOption

	if cfg.TLSEnabled {
		tlsCfg, err := loadClientTLS(cfg.CertFile, cfg.KeyFile, cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("load client TLS: %w", err)
		}
		opts = append(opts, grpc.WithTransportCredentials(credentials.NewTLS(tlsCfg)))
	} else {
		opts = append(opts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	}

	conn, err := grpc.NewClient(cfg.Addr, opts...)
	if err != nil {
		return nil, fmt.Errorf("grpc dial %s: %w", cfg.Addr, err)
	}

	return &AggregationClient{
		conn: conn,
		stub: pb.NewAggregationServiceClient(conn),
		log:  log,
	}, nil
}

// StartRound calls AggregationService.StartRound.
func (c *AggregationClient) StartRound(ctx context.Context, roundID, modelVersion string, minClients int32, deadlineUnix int64) (*pb.StartRoundResp, error) {
	req := &pb.StartRoundReq{
		RoundId:      roundID,
		ModelVersion: modelVersion,
		Config: &pb.RoundConfig{
			MinClients:   minClients,
			DeadlineUnix: deadlineUnix,
			Dp: &pb.DPConfig{
				Epsilon:  1.0,
				Delta:    1e-5,
				ClipNorm: 1.0,
			},
			FedproxMu: 0.01,
		},
	}

	c.log.Info("calling StartRound", "round_id", roundID, "model_version", modelVersion)
	resp, err := c.stub.StartRound(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("StartRound RPC: %w", err)
	}
	return resp, nil
}

// GetRoundState queries the round state from the aggregation server via GetGlobalModel.
// We use the Redis round state key pattern directly — but since orchestration
// doesn't have direct Redis access, we track state in PostgreSQL.
// For current round state, the handler queries Redis via the aggregation server's
// round state tracking.

// Close closes the gRPC connection.
func (c *AggregationClient) Close() error {
	return c.conn.Close()
}

func loadClientTLS(certFile, keyFile, caFile string) (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("load client cert: %w", err)
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
		RootCAs:      caPool,
		MinVersion:   tls.VersionTLS12,
	}, nil
}
