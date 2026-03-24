package watch

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/x9z0/fls/straggler-watch/internal/metrics"
)

const (
	ChannelRoundEvents = "fl:round:events"
	StragglerStream    = "fl:straggler:stream"
)

// RoundEvent is published on the fl:round:events channel.
type RoundEvent struct {
	Event        string `json:"event"`
	RoundID      string `json:"round_id"`
	DeadlineUnix int64  `json:"deadline_unix,omitempty"`
}

// Watcher subscribes to Redis round events and spawns per-round deadline goroutines.
type Watcher struct {
	rdb *redis.Client
	log *slog.Logger

	mu       sync.Mutex
	cancels  map[string]context.CancelFunc // round_id → cancel fn
}

// New creates a Watcher.
func New(rdb *redis.Client, log *slog.Logger) *Watcher {
	return &Watcher{
		rdb:     rdb,
		log:     log,
		cancels: make(map[string]context.CancelFunc),
	}
}

// Run subscribes to fl:round:events and dispatches goroutines. Blocks until ctx is cancelled.
func (w *Watcher) Run(ctx context.Context) error {
	sub := w.rdb.Subscribe(ctx, ChannelRoundEvents)
	defer sub.Close()

	ch := sub.Channel()
	w.log.Info("subscribed to round events", "channel", ChannelRoundEvents)

	for {
		select {
		case <-ctx.Done():
			w.cancelAll()
			return ctx.Err()
		case msg, ok := <-ch:
			if !ok {
				return fmt.Errorf("subscription channel closed")
			}
			w.handleMessage(ctx, msg.Payload)
		}
	}
}

func (w *Watcher) handleMessage(ctx context.Context, payload string) {
	var evt RoundEvent
	if err := json.Unmarshal([]byte(payload), &evt); err != nil {
		w.log.Warn("invalid event JSON", "error", err, "payload", payload)
		return
	}

	switch evt.Event {
	case "ROUND_OPENED", "ROUND_OPEN":
		w.onRoundOpen(ctx, evt)
	case "ROUND_CLOSED", "ROUND_CLOSE":
		w.onRoundClose(evt.RoundID)
	}
}

func (w *Watcher) onRoundOpen(parentCtx context.Context, evt RoundEvent) {
	roundID := evt.RoundID
	if roundID == "" {
		return
	}

	deadline := time.Unix(evt.DeadlineUnix, 0)

	// Also try reading from round config if deadline not in event
	if evt.DeadlineUnix == 0 {
		dl, err := w.readDeadlineFromConfig(parentCtx, roundID)
		if err != nil || dl == 0 {
			w.log.Warn("no deadline for round, skipping watch", "round_id", roundID)
			return
		}
		deadline = time.Unix(dl, 0)
	}

	// Don't watch already-expired deadlines
	if time.Until(deadline) <= 0 {
		w.log.Info("deadline already passed, firing immediately", "round_id", roundID)
		go w.fireDeadline(context.Background(), roundID)
		return
	}

	w.mu.Lock()
	if _, exists := w.cancels[roundID]; exists {
		w.mu.Unlock()
		w.log.Debug("watcher already running", "round_id", roundID)
		return
	}

	ctx, cancel := context.WithCancel(parentCtx)
	w.cancels[roundID] = cancel
	w.mu.Unlock()

	metrics.ActiveWatchers.Inc()

	go func() {
		defer func() {
			metrics.ActiveWatchers.Dec()
			w.mu.Lock()
			delete(w.cancels, roundID)
			w.mu.Unlock()
		}()

		w.watchRound(ctx, roundID, deadline)
	}()

	w.log.Info("watching round deadline",
		"round_id", roundID,
		"deadline", deadline.Format(time.RFC3339),
		"wait", time.Until(deadline).Round(time.Second).String(),
	)
}

func (w *Watcher) onRoundClose(roundID string) {
	w.mu.Lock()
	cancel, exists := w.cancels[roundID]
	w.mu.Unlock()

	if exists {
		cancel()
		w.log.Info("cancelled watcher for closed round", "round_id", roundID)
	}
}

// watchRound blocks until deadline then fires straggler detection.
func (w *Watcher) watchRound(ctx context.Context, roundID string, deadline time.Time) {
	timer := time.NewTimer(time.Until(deadline))
	defer timer.Stop()

	select {
	case <-ctx.Done():
		// Round was closed early or watcher shutting down
		w.log.Info("watcher cancelled before deadline", "round_id", roundID)
		return
	case <-timer.C:
		w.fireDeadline(ctx, roundID)
	}
}

// fireDeadline detects stragglers, records them, and publishes ROUND_CLOSE.
func (w *Watcher) fireDeadline(ctx context.Context, roundID string) {
	w.log.Info("deadline reached, detecting stragglers", "round_id", roundID)

	// Use a fresh context if parent is cancelled
	opCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Read expected clients from round config
	expected := w.readExpectedClients(opCtx, roundID)

	// Read submitted updates
	updateKey := fmt.Sprintf("round:%s:updates", roundID)
	submitted, err := w.rdb.SMembers(opCtx, updateKey).Result()
	if err != nil {
		w.log.Error("read updates set failed", "error", err, "round_id", roundID)
	}

	submittedSet := toSet(submitted)

	// Identify stragglers
	var stragglers []string
	for _, clientID := range expected {
		if !submittedSet[clientID] {
			stragglers = append(stragglers, clientID)
		}
	}

	// Record stragglers in Redis set
	if len(stragglers) > 0 {
		stragglerKey := fmt.Sprintf("round:%s:stragglers", roundID)
		members := make([]interface{}, len(stragglers))
		for i, s := range stragglers {
			members[i] = s
		}
		w.rdb.SAdd(opCtx, stragglerKey, members...)
		w.rdb.Expire(opCtx, stragglerKey, 7*24*time.Hour)

		metrics.StragglerTotal.Add(float64(len(stragglers)))
	}

	w.log.Info("stragglers detected",
		"round_id", roundID,
		"total_expected", len(expected),
		"submitted", len(submitted),
		"stragglers", len(stragglers),
	)

	// Write to straggler stream
	w.rdb.XAdd(opCtx, &redis.XAddArgs{
		Stream: StragglerStream,
		Values: map[string]interface{}{
			"round_id":   roundID,
			"stragglers": strings.Join(stragglers, ","),
			"submitted":  strings.Join(submitted, ","),
			"timestamp":  time.Now().Unix(),
		},
	})

	// Update round state to CLOSED
	stateKey := fmt.Sprintf("round:%s:state", roundID)
	w.rdb.Set(opCtx, stateKey, "CLOSED", 7*24*time.Hour)

	// Publish ROUND_CLOSE event
	closeEvt, _ := json.Marshal(map[string]interface{}{
		"event":      "ROUND_CLOSED",
		"round_id":   roundID,
		"stragglers": stragglers,
		"closed_by":  "straggler-watch",
	})
	w.rdb.Publish(opCtx, ChannelRoundEvents, string(closeEvt))

	metrics.RoundsClosed.Inc()
}

// readDeadlineFromConfig reads deadline_unix from round config hash.
func (w *Watcher) readDeadlineFromConfig(ctx context.Context, roundID string) (int64, error) {
	configKey := fmt.Sprintf("round:%s:config", roundID)
	val, err := w.rdb.HGet(ctx, configKey, "deadline_unix").Result()
	if err != nil {
		return 0, err
	}
	var dl int64
	fmt.Sscanf(val, "%d", &dl)
	return dl, nil
}

// readExpectedClients reads the expected_clients list from round config.
func (w *Watcher) readExpectedClients(ctx context.Context, roundID string) []string {
	configKey := fmt.Sprintf("round:%s:config", roundID)
	val, err := w.rdb.HGet(ctx, configKey, "expected_clients").Result()
	if err != nil {
		w.log.Debug("no expected_clients in config", "round_id", roundID)
		return nil
	}

	var clients []string
	if err := json.Unmarshal([]byte(val), &clients); err != nil {
		// Try comma-separated fallback
		clients = strings.Split(val, ",")
	}
	return clients
}

func (w *Watcher) cancelAll() {
	w.mu.Lock()
	defer w.mu.Unlock()
	for roundID, cancel := range w.cancels {
		cancel()
		delete(w.cancels, roundID)
	}
}

func toSet(items []string) map[string]bool {
	s := make(map[string]bool, len(items))
	for _, item := range items {
		s[item] = true
	}
	return s
}
