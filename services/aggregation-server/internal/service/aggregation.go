package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	minioclient "github.com/x9z0/fls/aggregation-server/internal/minio"
	"github.com/x9z0/fls/aggregation-server/internal/round"
	"github.com/x9z0/fls/aggregation-server/internal/store"
	pb "github.com/x9z0/fls/proto"
)

// Prometheus metrics
var (
	updatesAccepted = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_updates_accepted_total",
		Help: "Total number of accepted client updates",
	})
	updatesRejected = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "fl_updates_rejected_total",
		Help: "Total number of rejected client updates",
	}, []string{"reason"})
	participatingClients = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "fl_participating_clients",
		Help: "Number of clients that submitted updates in the current round",
	})
	roundDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "fl_round_duration_seconds",
		Help:    "Duration of FL rounds",
		Buckets: prometheus.ExponentialBuckets(10, 2, 8), // 10s to ~2560s
	})
)

// AggregationServer implements the gRPC AggregationServiceServer interface.
type AggregationServer struct {
	pb.UnimplementedAggregationServiceServer

	redis           *store.Store
	minio           *minioclient.Client
	rounds          *round.Manager
	log             *slog.Logger
	registryURL     string // client-registry base URL
	inferenceURL    string // inference-server base URL
}

// Config holds configuration for the aggregation server.
type Config struct {
	RegistryURL  string // e.g. "http://client-registry:8081"
	InferenceURL string // e.g. "http://inference-server:8000"
}

// NewAggregationServer creates a new server instance.
func NewAggregationServer(redis *store.Store, minio *minioclient.Client, cfg Config, log *slog.Logger) *AggregationServer {
	return &AggregationServer{
		redis:        redis,
		minio:        minio,
		rounds:       round.NewManager(),
		log:          log,
		registryURL:  cfg.RegistryURL,
		inferenceURL: cfg.InferenceURL,
	}
}

// ── RegisterClient ──────────────────────────────────────────────────────────

func (s *AggregationServer) RegisterClient(ctx context.Context, req *pb.RegisterReq) (*pb.RegisterResp, error) {
	s.log.Info("RegisterClient", "client_id", req.ClientId, "device_class", req.DeviceClass)

	// Forward to client-registry HTTP service
	body := map[string]interface{}{
		"device_class": req.DeviceClass,
	}
	if req.Caps != nil {
		body["caps"] = map[string]interface{}{
			"ram_mb":         req.Caps.RamMb,
			"has_gpu":        req.Caps.HasGpu,
			"cpu_cores":      req.Caps.CpuCores,
			"os":             req.Caps.Os,
			"can_train":      req.Caps.CanTrain,
			"vocab_size_cap": req.Caps.VocabSizeCap,
		}
	}

	jsonBody, _ := json.Marshal(body)
	httpReq, err := http.NewRequestWithContext(ctx, "POST",
		s.registryURL+"/clients/register", bytes.NewReader(jsonBody))
	if err != nil {
		return &pb.RegisterResp{Ok: false}, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		s.log.Error("registry call failed", "error", err)
		return &pb.RegisterResp{Ok: false}, nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		s.log.Error("registry returned error", "status", resp.StatusCode)
		return &pb.RegisterResp{Ok: false}, nil
	}

	var regResp struct {
		ClientID string `json:"client_id"`
		JWTToken string `json:"jwt_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&regResp); err != nil {
		return &pb.RegisterResp{Ok: false}, nil
	}

	// Initialize DP budget in Redis
	s.redis.UpdateClientBudget(ctx, regResp.ClientID, 0)

	return &pb.RegisterResp{
		Ok:               true,
		AssignedClientId: regResp.ClientID,
	}, nil
}

// ── StartRound ──────────────────────────────────────────────────────────────

func (s *AggregationServer) StartRound(ctx context.Context, req *pb.StartRoundReq) (*pb.StartRoundResp, error) {
	s.log.Info("StartRound", "round_id", req.RoundId, "model_version", req.ModelVersion)

	// CAS: only create if round doesn't exist
	created, err := s.redis.SetRoundStateNX(ctx, req.RoundId, string(round.StateOpen))
	if err != nil {
		return nil, fmt.Errorf("set round state: %w", err)
	}
	if !created {
		return &pb.StartRoundResp{
			Ok:      false,
			RoundId: req.RoundId,
		}, nil
	}

	// Track in-memory FSM
	s.rounds.GetOrCreate(req.RoundId, round.StateOpen)

	// Store round config
	cfg := map[string]interface{}{
		"base_model_version": req.ModelVersion,
		"opened_at":          time.Now().Unix(),
	}
	if req.Config != nil {
		cfg["min_clients"] = req.Config.MinClients
		cfg["deadline_unix"] = req.Config.DeadlineUnix
		if req.Config.Dp != nil {
			cfg["dp_target_epsilon"] = req.Config.Dp.Epsilon
			cfg["dp_delta"] = req.Config.Dp.Delta
		}
		cfg["fedprox_mu"] = req.Config.FedproxMu
	}
	s.redis.SetRoundConfig(ctx, req.RoundId, cfg)

	// Set straggler deadline if configured
	if req.Config != nil && req.Config.DeadlineUnix > 0 {
		deadline := time.Unix(req.Config.DeadlineUnix, 0)
		s.redis.SetStragglerDeadline(ctx, req.RoundId, deadline)
	}

	// Generate presigned model URL
	version := req.ModelVersion
	if version == "" {
		version, _ = s.redis.GetCurrentModelVersion(ctx)
	}
	modelURL, err := s.minio.ModelPresignedURL(ctx, version)
	if err != nil {
		s.log.Error("presign model URL", "error", err)
		modelURL = ""
	}

	// Publish round event
	s.redis.PublishRoundEvent(ctx, map[string]interface{}{
		"event":    "ROUND_OPENED",
		"round_id": req.RoundId,
		"version":  version,
	})

	deadline := int64(0)
	if req.Config != nil {
		deadline = req.Config.DeadlineUnix
	}

	return &pb.StartRoundResp{
		Ok:       true,
		ModelUrl: modelURL,
		Deadline: deadline,
		RoundId:  req.RoundId,
	}, nil
}

// ── GetGlobalModel ──────────────────────────────────────────────────────────

func (s *AggregationServer) GetGlobalModel(ctx context.Context, req *pb.GetModelReq) (*pb.GetModelResp, error) {
	version := req.ModelVersion
	if version == "" {
		var err error
		version, err = s.redis.GetCurrentModelVersion(ctx)
		if err != nil || version == "" {
			return nil, fmt.Errorf("no current model version")
		}
	}

	meta, err := s.redis.GetModelMeta(ctx, version)
	if err != nil {
		return nil, fmt.Errorf("get model meta: %w", err)
	}

	modelURL, err := s.minio.ModelPresignedURL(ctx, version)
	if err != nil {
		return nil, fmt.Errorf("presign model: %w", err)
	}

	vocabURL, err := s.minio.VocabPresignedURL(ctx)
	if err != nil {
		s.log.Warn("presign vocab failed", "error", err)
	}

	metaJSON, _ := json.Marshal(meta)

	return &pb.GetModelResp{
		ModelUrl:  modelURL,
		ModelMeta: metaJSON,
		VocabUrl:  vocabURL,
	}, nil
}

// ── SubmitUpdate ────────────────────────────────────────────────────────────

func (s *AggregationServer) SubmitUpdate(ctx context.Context, req *pb.SubmitUpdateReq) (*pb.SubmitUpdateResp, error) {
	s.log.Info("SubmitUpdate", "round_id", req.RoundId, "client_id", req.ClientId)

	// Check round state
	state, err := s.redis.GetRoundState(ctx, req.RoundId)
	if err != nil {
		return nil, fmt.Errorf("get round state: %w", err)
	}
	if state == "" {
		updatesRejected.WithLabelValues("round_not_found").Inc()
		return &pb.SubmitUpdateResp{Accepted: false, Reason: "round_not_found"}, nil
	}
	if state != string(round.StateOpen) && state != string(round.StateCollecting) {
		updatesRejected.WithLabelValues("round_closed").Inc()
		return &pb.SubmitUpdateResp{Accepted: false, Reason: "round_closed"}, nil
	}

	// Verify checksum
	if req.Meta != nil && req.Meta.Checksum != "" {
		h := sha256.Sum256(req.UpdateBlob)
		expected := "sha256:" + fmt.Sprintf("%x", h)
		if req.Meta.Checksum != expected {
			updatesRejected.WithLabelValues("checksum_mismatch").Inc()
			return &pb.SubmitUpdateResp{Accepted: false, Reason: "checksum_mismatch"}, nil
		}
	}

	// Idempotency: SADD returns false if client already submitted
	added, err := s.redis.AddUpdate(ctx, req.RoundId, req.ClientId)
	if err != nil {
		return nil, fmt.Errorf("add update: %w", err)
	}
	if !added {
		updatesRejected.WithLabelValues("duplicate").Inc()
		return &pb.SubmitUpdateResp{Accepted: false, Reason: "duplicate"}, nil
	}

	// Upload blob to MinIO
	blobKey := minioclient.UpdateBlobKey(req.RoundId, req.ClientId)
	reader := bytes.NewReader(req.UpdateBlob)
	if err := s.minio.PutObject(ctx, minioclient.BucketModels, blobKey, reader, int64(len(req.UpdateBlob)), "application/octet-stream"); err != nil {
		s.log.Error("upload update blob", "error", err)
		// Still count as accepted — blob can be retried
	}

	// Update DP budget in Redis
	if req.Meta != nil && req.Meta.DpEpsilon > 0 {
		s.redis.UpdateClientBudget(ctx, req.ClientId, req.Meta.DpEpsilon)
	}

	// Update metrics
	updatesAccepted.Inc()
	count, _ := s.redis.GetUpdateCount(ctx, req.RoundId)
	participatingClients.Set(float64(count))

	// Transition to COLLECTING if first update in OPEN round
	if m := s.rounds.Get(req.RoundId); m != nil {
		if m.State() == round.StateOpen {
			m.Transition(round.StateCollecting)
			s.redis.SetRoundState(ctx, req.RoundId, string(round.StateCollecting))
		}
	}

	return &pb.SubmitUpdateResp{Accepted: true, Reason: "ok"}, nil
}

// ── EmitMetrics ─────────────────────────────────────────────────────────────

func (s *AggregationServer) EmitMetrics(ctx context.Context, req *pb.MetricsReq) (*pb.MetricsResp, error) {
	s.log.Info("EmitMetrics",
		"client_id", req.ClientId,
		"round_id", req.RoundId,
		"train_duration", req.LocalTrainDurationS,
		"samples", req.SamplesTrained,
		"epsilon_spent", req.DpEpsilonSpent,
	)

	// Log metrics — in production, push to Prometheus pushgateway
	// For now, metrics are exposed via /metrics endpoint on the server

	return &pb.MetricsResp{Ok: true}, nil
}

// ── Infer ───────────────────────────────────────────────────────────────────

func (s *AggregationServer) Infer(ctx context.Context, req *pb.InferReq) (*pb.InferResp, error) {
	// Proxy to inference server
	topK := req.TopK
	if topK == 0 {
		topK = 3
	}

	body := map[string]interface{}{
		"token_ids": req.TokenIds,
		"top_k":     topK,
	}
	jsonBody, _ := json.Marshal(body)

	httpReq, err := http.NewRequestWithContext(ctx, "POST",
		s.inferenceURL+"/infer", bytes.NewReader(jsonBody))
	if err != nil {
		return nil, fmt.Errorf("build infer request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		s.log.Error("inference proxy failed", "error", err)
		return &pb.InferResp{}, nil
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var inferResp struct {
		Suggestions []string  `json:"suggestions"`
		Scores      []float32 `json:"scores"`
	}
	json.Unmarshal(respBody, &inferResp)

	return &pb.InferResp{
		Suggestions: inferResp.Suggestions,
		Scores:      inferResp.Scores,
	}, nil
}

// RoundDurationObserve records the duration of a completed round.
func RoundDurationObserve(startUnix int64) {
	elapsed := float64(time.Now().Unix() - startUnix)
	roundDuration.Observe(elapsed)
}

