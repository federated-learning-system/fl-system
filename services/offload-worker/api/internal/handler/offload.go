package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/minio/minio-go/v7"
	"github.com/redis/go-redis/v9"
)

const (
	streamKey       = "fl:offload:jobs"
	consumerGroup   = "offload-trainers"
	bucketOffload   = "fl-offload"
	presignTTL      = 10 * time.Minute
)

// CreateJobReq is the request body for POST /offload/jobs.
type CreateJobReq struct {
	ClientID           string                   `json:"client_id"`
	DeviceClass        string                   `json:"device_class"`
	RoundID            string                   `json:"round_id"`
	ModelVersion       string                   `json:"model_version"`
	NumSamples         int                      `json:"num_samples,omitempty"`
	FrequencyHistogram []FrequencyBucket        `json:"frequency_histogram,omitempty"`
}

type FrequencyBucket struct {
	TokenRange string `json:"token_range"`
	Count      int    `json:"count"`
}

// CreateJobResp is the response body for POST /offload/jobs.
type CreateJobResp struct {
	JobID     string `json:"job_id"`
	UploadURL string `json:"upload_url,omitempty"`
}

// StatusResp is the response body for GET /offload/jobs/{id}.
type StatusResp struct {
	Status string `json:"status"`
}

// Handler holds dependencies for the offload API handlers.
type Handler struct {
	rdb *redis.Client
	mc  *minio.Client
	log *slog.Logger
}

// New creates a new Handler.
func New(rdb *redis.Client, mc *minio.Client, log *slog.Logger) *Handler {
	return &Handler{rdb: rdb, mc: mc, log: log}
}

// EnsureStream creates the consumer group if it doesn't already exist.
func (h *Handler) EnsureStream(ctx context.Context) {
	err := h.rdb.XGroupCreateMkStream(ctx, streamKey, consumerGroup, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		h.log.Warn("failed to create consumer group", "error", err)
	}
}

// CreateJob handles POST /offload/jobs.
func (h *Handler) CreateJob(w http.ResponseWriter, r *http.Request) {
	var req CreateJobReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid json"}`, http.StatusBadRequest)
		return
	}

	if req.ClientID == "" || req.RoundID == "" || req.ModelVersion == "" {
		http.Error(w, `{"error":"client_id, round_id, model_version required"}`, http.StatusBadRequest)
		return
	}
	if req.DeviceClass == "" {
		req.DeviceClass = "LAPTOP_SIM"
	}

	jobID := "job-" + uuid.New().String()[:8]
	ctx := r.Context()

	resp := CreateJobResp{JobID: jobID}

	// Build stream fields
	fields := map[string]interface{}{
		"job_id":        jobID,
		"client_id":     req.ClientID,
		"device_class":  req.DeviceClass,
		"round_id":      req.RoundID,
		"model_version": req.ModelVersion,
		"num_samples":   fmt.Sprintf("%d", req.NumSamples),
	}

	// For LAPTOP_SIM: generate presigned PUT URL for token batch upload
	if req.DeviceClass == "LAPTOP_SIM" || req.DeviceClass == "ANDROID" {
		objectKey := fmt.Sprintf("offload-jobs/%s/tokens.json", jobID)
		uploadURL, err := h.mc.PresignedPutObject(ctx, bucketOffload, objectKey, presignTTL)
		if err != nil {
			h.log.Error("presign PUT failed", "error", err)
			http.Error(w, `{"error":"presign failed"}`, http.StatusInternalServerError)
			return
		}
		resp.UploadURL = uploadURL.String()
		fields["upload_key"] = objectKey
	}

	// For ESP32: embed frequency histogram in stream fields
	if req.DeviceClass == "ESP32" && req.FrequencyHistogram != nil {
		histJSON, _ := json.Marshal(req.FrequencyHistogram)
		fields["frequency_histogram"] = string(histJSON)
	}

	// Set initial job status
	statusKey := fmt.Sprintf("offload:job:%s:status", jobID)
	h.rdb.Set(ctx, statusKey, "QUEUED", 1*time.Hour)

	// XADD to stream
	if err := h.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: streamKey,
		Values: fields,
	}).Err(); err != nil {
		h.log.Error("XADD failed", "error", err)
		http.Error(w, `{"error":"stream write failed"}`, http.StatusInternalServerError)
		return
	}

	h.log.Info("job created", "job_id", jobID, "device_class", req.DeviceClass, "client_id", req.ClientID)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// GetJobStatus handles GET /offload/jobs/{id}.
func (h *Handler) GetJobStatus(w http.ResponseWriter, r *http.Request) {
	jobID := chi.URLParam(r, "id")
	if jobID == "" {
		http.Error(w, `{"error":"missing job id"}`, http.StatusBadRequest)
		return
	}

	statusKey := fmt.Sprintf("offload:job:%s:status", jobID)
	status, err := h.rdb.Get(r.Context(), statusKey).Result()
	if err == redis.Nil {
		http.Error(w, `{"error":"job not found"}`, http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, `{"error":"redis error"}`, http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(StatusResp{Status: status})
}

// Healthz handles GET /healthz.
func (h *Handler) Healthz(w http.ResponseWriter, r *http.Request) {
	if err := h.rdb.Ping(r.Context()).Err(); err != nil {
		http.Error(w, "unhealthy", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("ok"))
}
