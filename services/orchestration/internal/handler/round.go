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

	"github.com/x9z0/fls/orchestration/internal/grpcclient"
	"github.com/x9z0/fls/orchestration/internal/store"
)

// Handler holds dependencies for HTTP route handlers.
type Handler struct {
	store       *store.Store
	aggClient   *grpcclient.AggregationClient
	registryURL string
	log         *slog.Logger
	minClients  int32
}

// Config for creating a Handler.
type Config struct {
	RegistryURL string
	MinClients  int32
}

// New creates a Handler.
func New(s *store.Store, agg *grpcclient.AggregationClient, cfg Config, log *slog.Logger) *Handler {
	return &Handler{
		store:       s,
		aggClient:   agg,
		registryURL: cfg.RegistryURL,
		log:         log,
		minClients:  cfg.MinClients,
	}
}

// currentRoundID tracks the most recently started round.
var currentRoundID string

// StartRound handles POST /rounds/start — manually trigger a new round.
func (h *Handler) StartRound(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	roundID, modelVersion, err := h.startRoundLogic(ctx)
	if err != nil {
		h.log.Error("start round failed", "error", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{
			"error": err.Error(),
		})
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"round_id":      roundID,
		"model_version": modelVersion,
		"state":         "OPEN",
	})
}

// CloseRound handles POST /rounds/{id}/close — manually close a round.
func (h *Handler) CloseRound(w http.ResponseWriter, r *http.Request) {
	roundID := chi.URLParam(r, "id")
	if roundID == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing round id"})
		return
	}

	ctx := r.Context()
	if err := h.store.UpdateRoundState(ctx, roundID, "CLOSED"); err != nil {
		h.log.Error("close round failed", "error", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"round_id": roundID,
		"state":    "CLOSED",
	})
}

// CurrentRound handles GET /rounds/current — returns the most recent round state.
func (h *Handler) CurrentRound(w http.ResponseWriter, r *http.Request) {
	if currentRoundID == "" {
		writeJSON(w, http.StatusOK, map[string]string{
			"round_id": "",
			"state":    "NONE",
		})
		return
	}

	ctx := r.Context()
	round, err := h.store.GetRound(ctx, currentRoundID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if round == nil {
		writeJSON(w, http.StatusOK, map[string]string{
			"round_id": currentRoundID,
			"state":    "UNKNOWN",
		})
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"round_id":      round.RoundID,
		"state":         round.State,
		"model_version": round.ModelVersion,
		"started_at":    round.StartedAt.Format(time.RFC3339),
	})
}

// History handles GET /rounds/history — returns last 10 rounds.
func (h *Handler) History(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	rounds, err := h.store.ListRecentRounds(ctx, 10)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if rounds == nil {
		rounds = []store.Round{}
	}
	writeJSON(w, http.StatusOK, rounds)
}

// Healthz handles GET /healthz.
func (h *Handler) Healthz(w http.ResponseWriter, r *http.Request) {
	if err := h.store.Ping(r.Context()); err != nil {
		http.Error(w, "db unhealthy", http.StatusServiceUnavailable)
		return
	}
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("ok"))
}

// StartRoundCron is the cron-triggered round start logic.
func (h *Handler) StartRoundCron() {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	roundID, _, err := h.startRoundLogic(ctx)
	if err != nil {
		h.log.Error("cron round start failed", "error", err)
		return
	}
	h.log.Info("cron round started", "round_id", roundID)
}

// startRoundLogic is the shared logic for starting a round.
func (h *Handler) startRoundLogic(ctx context.Context) (string, string, error) {
	// 1. Check eligible clients
	eligible, err := h.fetchEligibleClients(ctx)
	if err != nil {
		return "", "", fmt.Errorf("fetch eligible clients: %w", err)
	}

	if int32(len(eligible)) < h.minClients {
		h.log.Info("not enough eligible clients",
			"eligible", len(eligible),
			"min_required", h.minClients,
		)
		// Still proceed for manual triggers — log the warning but allow
		// For cron, we could skip, but manual POST should always work
	}

	// 2. Generate round ID
	uid := uuid.New().String()[:8]
	roundID := "round-" + time.Now().Format("2006-01-02") + "-" + uid

	// 3. Get current model version (default to v1.0.0)
	modelVersion := "v1.0.0"

	// 4. Set deadline 60 minutes from now
	deadline := time.Now().Add(60 * time.Minute).Unix()

	// 5. Call AggregationService.StartRound via gRPC
	resp, err := h.aggClient.StartRound(ctx, roundID, modelVersion, h.minClients, deadline)
	if err != nil {
		return "", "", fmt.Errorf("gRPC StartRound: %w", err)
	}
	if !resp.Ok {
		return "", "", fmt.Errorf("StartRound rejected: round_id=%s", resp.RoundId)
	}

	// 6. Record in PostgreSQL
	config := map[string]interface{}{
		"min_clients":   h.minClients,
		"deadline_unix": deadline,
		"eligible":      len(eligible),
	}
	if err := h.store.InsertRound(ctx, roundID, modelVersion, "OPEN", config); err != nil {
		h.log.Error("insert round to postgres failed", "error", err, "round_id", roundID)
		// Non-fatal — round already started in aggregation server
	}

	// Track current round
	currentRoundID = roundID

	h.log.Info("round started",
		"round_id", roundID,
		"model_version", modelVersion,
		"eligible_clients", len(eligible),
	)

	return roundID, modelVersion, nil
}

// fetchEligibleClients calls the client-registry /clients/eligible endpoint.
func (h *Handler) fetchEligibleClients(ctx context.Context) ([]map[string]interface{}, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", h.registryURL+"/clients/eligible", nil)
	if err != nil {
		return nil, err
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		h.log.Warn("client-registry unreachable", "error", err)
		return nil, nil // non-fatal — proceed with empty list
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		h.log.Warn("client-registry error", "status", resp.StatusCode)
		return nil, nil
	}

	var clients []map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&clients); err != nil {
		return nil, nil
	}
	return clients, nil
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
