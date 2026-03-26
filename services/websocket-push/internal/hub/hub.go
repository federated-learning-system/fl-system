package hub

import (
	"log/slog"
	"sync"
)

// Client represents a connected WebSocket client.
type Client struct {
	Send chan []byte
	id   string
}

// NewClient creates a new Client with a buffered send channel.
func NewClient(id string) *Client {
	return &Client{
		Send: make(chan []byte, 64),
		id:   id,
	}
}

// Hub maintains the set of active clients and broadcasts messages to them.
// A single goroutine runs Hub.Run() — all client state is managed via channels.
type Hub struct {
	clients    map[*Client]struct{}
	Broadcast  chan []byte
	Register   chan *Client
	Unregister chan *Client

	mu  sync.RWMutex // only for Count()
	log *slog.Logger
}

// New creates a new Hub.
func New(log *slog.Logger) *Hub {
	return &Hub{
		clients:    make(map[*Client]struct{}),
		Broadcast:  make(chan []byte, 256),
		Register:   make(chan *Client),
		Unregister: make(chan *Client),
		log:        log,
	}
}

// Run loops on select{} — single goroutine manages all client state safely.
func (h *Hub) Run() {
	for {
		select {
		case c := <-h.Register:
			h.mu.Lock()
			h.clients[c] = struct{}{}
			h.mu.Unlock()
			h.log.Info("client connected", "client_id", c.id, "total", h.Count())

		case c := <-h.Unregister:
			h.mu.Lock()
			if _, ok := h.clients[c]; ok {
				delete(h.clients, c)
				close(c.Send)
			}
			h.mu.Unlock()
			h.log.Info("client disconnected", "client_id", c.id, "total", h.Count())

		case msg := <-h.Broadcast:
			h.mu.RLock()
			for c := range h.clients {
				select {
				case c.Send <- msg:
				default:
					// Slow client — drop it
					delete(h.clients, c)
					close(c.Send)
					h.log.Warn("dropped slow client", "client_id", c.id)
				}
			}
			h.mu.RUnlock()
		}
	}
}

// Count returns the number of connected clients.
func (h *Hub) Count() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.clients)
}
