package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"

	"github.com/x9z0/fls/websocket-push/internal/hub"
)

const (
	writeWait  = 10 * time.Second
	pongWait   = 60 * time.Second
	pingPeriod = (pongWait * 9) / 10
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins for FL clients
	},
}

// Handler holds the hub and logger.
type Handler struct {
	Hub *hub.Hub
	Log *slog.Logger
}

// ServeWS upgrades HTTP to WebSocket and registers the client.
func (h *Handler) ServeWS(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		h.Log.Error("websocket upgrade failed", "error", err)
		return
	}

	clientID := r.URL.Query().Get("client_id")
	if clientID == "" {
		clientID = "anon-" + uuid.New().String()[:8]
	}

	client := hub.NewClient(clientID)
	h.Hub.Register <- client

	// Start read and write pumps in separate goroutines
	go h.writePump(conn, client)
	go h.readPump(conn, client)
}

// Connections returns the number of active WebSocket connections.
func (h *Handler) Connections(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]int{
		"count": h.Hub.Count(),
	})
}

// readPump pumps messages from the WebSocket to the hub.
// We don't expect inbound messages, but we need to read to detect close.
func (h *Handler) readPump(conn *websocket.Conn, client *hub.Client) {
	defer func() {
		h.Hub.Unregister <- client
		conn.Close()
	}()

	conn.SetReadLimit(512)
	conn.SetReadDeadline(time.Now().Add(pongWait))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})

	for {
		_, _, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				h.Log.Warn("websocket read error", "error", err)
			}
			break
		}
	}
}

// writePump pumps messages from the hub to the WebSocket connection.
func (h *Handler) writePump(conn *websocket.Conn, client *hub.Client) {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		conn.Close()
	}()

	for {
		select {
		case msg, ok := <-client.Send:
			conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				// Hub closed the channel
				conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}

		case <-ticker.C:
			conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}
