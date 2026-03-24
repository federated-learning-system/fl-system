package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/x9z0/fls/client-registry/internal/auth"
	"github.com/x9z0/fls/client-registry/internal/store"
)

// Handler holds dependencies for HTTP handlers.
type Handler struct {
	store *store.Store
	jwt   *auth.JWTAuth
	log   *slog.Logger
}

// New creates a Handler with the given dependencies.
func New(s *store.Store, j *auth.JWTAuth, log *slog.Logger) *Handler {
	return &Handler{store: s, jwt: j, log: log}
}

// --- Request / Response types ---

type registerReq struct {
	DeviceClass string            `json:"device_class"`
	Caps        store.Capabilities `json:"caps"`
}

type registerResp struct {
	ClientID string `json:"client_id"`
	JWTToken string `json:"jwt_token"`
}

type budgetReq struct {
	EpsilonSpent float64 `json:"epsilon_spent"`
}

type errorResp struct {
	Error string `json:"error"`
}

// --- Handlers ---

// Register handles POST /clients/register.
func (h *Handler) Register(w http.ResponseWriter, r *http.Request) {
	var req registerReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, errorResp{Error: "invalid request body"})
		return
	}
	if req.DeviceClass == "" {
		writeJSON(w, http.StatusBadRequest, errorResp{Error: "device_class is required"})
		return
	}

	clientID := "client-" + uuid.New().String()[:8]

	client, err := h.store.InsertClient(r.Context(), clientID, req.DeviceClass, req.Caps)
	if err != nil {
		h.log.Error("insert client", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorResp{Error: "failed to register client"})
		return
	}

	token, err := h.jwt.Issue(client.ClientID)
	if err != nil {
		h.log.Error("issue jwt", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorResp{Error: "failed to issue token"})
		return
	}

	writeJSON(w, http.StatusOK, registerResp{
		ClientID: client.ClientID,
		JWTToken: token,
	})
}

// GetClient handles GET /clients/{id}.
func (h *Handler) GetClient(w http.ResponseWriter, r *http.Request) {
	clientID := chi.URLParam(r, "id")
	client, err := h.store.GetClient(r.Context(), clientID)
	if err != nil {
		h.log.Error("get client", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorResp{Error: "database error"})
		return
	}
	if client == nil {
		writeJSON(w, http.StatusNotFound, errorResp{Error: "client not found"})
		return
	}
	writeJSON(w, http.StatusOK, client)
}

// Heartbeat handles PUT /clients/{id}/heartbeat.
func (h *Handler) Heartbeat(w http.ResponseWriter, r *http.Request) {
	clientID := chi.URLParam(r, "id")

	// Verify the JWT subject matches the path parameter
	claims := auth.ClaimsFromContext(r.Context())
	if claims == nil || claims.ClientID != clientID {
		writeJSON(w, http.StatusForbidden, errorResp{Error: "token does not match client_id"})
		return
	}

	if err := h.store.UpdateHeartbeat(r.Context(), clientID); err != nil {
		h.log.Error("heartbeat", "error", err)
		writeJSON(w, http.StatusNotFound, errorResp{Error: "client not found"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// Eligible handles GET /clients/eligible.
func (h *Handler) Eligible(w http.ResponseWriter, r *http.Request) {
	clients, err := h.store.ListEligible(r.Context())
	if err != nil {
		h.log.Error("list eligible", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorResp{Error: "database error"})
		return
	}
	if clients == nil {
		clients = []store.Client{}
	}
	writeJSON(w, http.StatusOK, clients)
}

// UpdateBudget handles POST /clients/{id}/budget.
func (h *Handler) UpdateBudget(w http.ResponseWriter, r *http.Request) {
	clientID := chi.URLParam(r, "id")

	claims := auth.ClaimsFromContext(r.Context())
	if claims == nil || claims.ClientID != clientID {
		writeJSON(w, http.StatusForbidden, errorResp{Error: "token does not match client_id"})
		return
	}

	var req budgetReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, errorResp{Error: "invalid request body"})
		return
	}
	if req.EpsilonSpent <= 0 {
		writeJSON(w, http.StatusBadRequest, errorResp{Error: "epsilon_spent must be positive"})
		return
	}

	if err := h.store.UpdateBudget(r.Context(), clientID, req.EpsilonSpent); err != nil {
		h.log.Error("update budget", "error", err)
		writeJSON(w, http.StatusNotFound, errorResp{Error: "client not found"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// RefreshToken handles POST /auth/refresh.
func (h *Handler) RefreshToken(w http.ResponseWriter, r *http.Request) {
	claims := auth.ClaimsFromContext(r.Context())
	if claims == nil {
		writeJSON(w, http.StatusUnauthorized, errorResp{Error: "missing claims"})
		return
	}

	token, err := h.jwt.Issue(claims.ClientID)
	if err != nil {
		h.log.Error("refresh jwt", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorResp{Error: "failed to issue token"})
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"client_id": claims.ClientID,
		"jwt_token": token,
	})
}

// Healthz handles GET /healthz.
func (h *Handler) Healthz(w http.ResponseWriter, r *http.Request) {
	if err := h.store.Ping(r.Context()); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, errorResp{Error: "database unreachable"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
