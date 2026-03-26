package store

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"
)

// Redis key patterns — mirrors services/shared/redis_client.py
const (
	KeyModelCurrent  = "model:current"
	KeyModelVersion  = "model:version:%s"  // model:version:{v}
	KeyRoundState    = "round:%s:state"    // round:{id}:state
	KeyRoundUpdates  = "round:%s:updates"  // round:{id}:updates (SET)
	KeyRoundConfig   = "round:%s:config"   // round:{id}:config  (HASH)
	KeyClientBudget  = "client:%s:budget"  // client:{id}:budget (HASH)
	KeyStragglerDL   = "straggler:%s:deadline" // auto-expires

	ChannelRoundEvents  = "fl:round:events"
	ChannelModelUpdated = "fl:model:updated"

	RoundKeyTTL = 7 * 24 * time.Hour // 7 days
)

// Store wraps a go-redis client for aggregation-server operations.
type Store struct {
	rdb *redis.Client
	log *slog.Logger
}

// New creates a Redis store.
func New(addr string, log *slog.Logger) (*Store, error) {
	rdb := redis.NewClient(&redis.Options{
		Addr:         addr,
		DB:           0,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 5 * time.Second,
		PoolSize:     10,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := rdb.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping: %w", err)
	}

	return &Store{rdb: rdb, log: log}, nil
}

// Close the Redis connection.
func (s *Store) Close() error {
	return s.rdb.Close()
}

// Ping checks Redis health.
func (s *Store) Ping(ctx context.Context) error {
	return s.rdb.Ping(ctx).Err()
}

// ── Model operations ────────────────────────────────────────────────────────

// GetCurrentModelVersion returns the value of model:current.
func (s *Store) GetCurrentModelVersion(ctx context.Context) (string, error) {
	v, err := s.rdb.Get(ctx, KeyModelCurrent).Result()
	if err == redis.Nil {
		return "", nil
	}
	return v, err
}

// GetModelMeta returns the hash stored at model:version:{v}.
func (s *Store) GetModelMeta(ctx context.Context, version string) (map[string]string, error) {
	key := fmt.Sprintf(KeyModelVersion, version)
	return s.rdb.HGetAll(ctx, key).Result()
}

// ── Round operations ────────────────────────────────────────────────────────

// SetRoundState sets the round FSM state using SETNX for initial creation.
// Returns true if newly created, false if already exists.
func (s *Store) SetRoundStateNX(ctx context.Context, roundID, state string) (bool, error) {
	key := fmt.Sprintf(KeyRoundState, roundID)
	ok, err := s.rdb.SetNX(ctx, key, state, RoundKeyTTL).Result()
	return ok, err
}

// GetRoundState returns the current state of a round.
func (s *Store) GetRoundState(ctx context.Context, roundID string) (string, error) {
	key := fmt.Sprintf(KeyRoundState, roundID)
	v, err := s.rdb.Get(ctx, key).Result()
	if err == redis.Nil {
		return "", nil
	}
	return v, err
}

// SetRoundState overwrites the round state.
func (s *Store) SetRoundState(ctx context.Context, roundID, state string) error {
	key := fmt.Sprintf(KeyRoundState, roundID)
	return s.rdb.Set(ctx, key, state, RoundKeyTTL).Err()
}

// SetRoundConfig stores the round configuration hash.
func (s *Store) SetRoundConfig(ctx context.Context, roundID string, config map[string]interface{}) error {
	key := fmt.Sprintf(KeyRoundConfig, roundID)
	pipe := s.rdb.Pipeline()
	pipe.HSet(ctx, key, config)
	pipe.Expire(ctx, key, RoundKeyTTL)
	_, err := pipe.Exec(ctx)
	return err
}

// AddUpdate adds a client_id to the round's update set. Returns true if newly added.
func (s *Store) AddUpdate(ctx context.Context, roundID, clientID string) (bool, error) {
	key := fmt.Sprintf(KeyRoundUpdates, roundID)
	added, err := s.rdb.SAdd(ctx, key, clientID).Result()
	if err != nil {
		return false, err
	}
	s.rdb.Expire(ctx, key, RoundKeyTTL)
	return added > 0, nil
}

// GetUpdateCount returns how many updates have been submitted for a round.
func (s *Store) GetUpdateCount(ctx context.Context, roundID string) (int64, error) {
	key := fmt.Sprintf(KeyRoundUpdates, roundID)
	return s.rdb.SCard(ctx, key).Result()
}

// SetStragglerDeadline sets an auto-expiring key for the straggler watch.
func (s *Store) SetStragglerDeadline(ctx context.Context, roundID string, deadline time.Time) error {
	key := fmt.Sprintf(KeyStragglerDL, roundID)
	ttl := time.Until(deadline)
	if ttl <= 0 {
		ttl = 1 * time.Second
	}
	return s.rdb.Set(ctx, key, deadline.Unix(), ttl).Err()
}

// ── DP Budget ───────────────────────────────────────────────────────────────

// UpdateClientBudget increments the cumulative DP epsilon for a client.
func (s *Store) UpdateClientBudget(ctx context.Context, clientID string, epsilonSpent float64) error {
	key := fmt.Sprintf(KeyClientBudget, clientID)
	return s.rdb.HIncrByFloat(ctx, key, "dp_epsilon_cumulative", epsilonSpent).Err()
}

// ── Pub/Sub ─────────────────────────────────────────────────────────────────

// PublishRoundEvent publishes a JSON event to the round events channel.
func (s *Store) PublishRoundEvent(ctx context.Context, event map[string]interface{}) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}
	return s.rdb.Publish(ctx, ChannelRoundEvents, string(data)).Err()
}

// PublishModelUpdated publishes to the model updated channel.
func (s *Store) PublishModelUpdated(ctx context.Context, version string) error {
	data, _ := json.Marshal(map[string]string{"version": version})
	return s.rdb.Publish(ctx, ChannelModelUpdated, string(data)).Err()
}
