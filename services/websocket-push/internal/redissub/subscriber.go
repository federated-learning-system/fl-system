package redissub

import (
	"context"
	"log/slog"

	"github.com/redis/go-redis/v9"

	"github.com/x9z0/fls/websocket-push/internal/hub"
)

const (
	ChannelRoundEvents  = "fl:round:events"
	ChannelModelUpdated = "fl:model:updated"
)

// Subscriber listens to Redis Pub/Sub channels and forwards messages
// to the Hub's broadcast channel.
type Subscriber struct {
	rdb *redis.Client
	hub *hub.Hub
	log *slog.Logger
}

// New creates a new Subscriber.
func New(rdb *redis.Client, h *hub.Hub, log *slog.Logger) *Subscriber {
	return &Subscriber{rdb: rdb, hub: h, log: log}
}

// Run subscribes to Redis channels and forwards messages to the hub.
// Blocks until ctx is cancelled.
func (s *Subscriber) Run(ctx context.Context) error {
	pubsub := s.rdb.Subscribe(ctx, ChannelRoundEvents, ChannelModelUpdated)
	defer pubsub.Close()

	// Wait for subscription confirmation
	if _, err := pubsub.Receive(ctx); err != nil {
		return err
	}
	s.log.Info("subscribed to Redis channels",
		"channels", []string{ChannelRoundEvents, ChannelModelUpdated})

	ch := pubsub.Channel()
	for {
		select {
		case <-ctx.Done():
			s.log.Info("subscriber shutting down")
			return ctx.Err()
		case msg, ok := <-ch:
			if !ok {
				s.log.Warn("Redis pub/sub channel closed")
				return nil
			}
			s.log.Debug("redis message", "channel", msg.Channel, "payload_len", len(msg.Payload))
			s.hub.Broadcast <- []byte(msg.Payload)
		}
	}
}
