package store

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Round mirrors the rounds table in PostgreSQL.
type Round struct {
	RoundID          string     `json:"round_id"`
	ModelVersion     string     `json:"model_version"`
	StartedAt        time.Time  `json:"started_at"`
	ClosedAt         *time.Time `json:"closed_at,omitempty"`
	State            string     `json:"state"`
	ConfigJSON       *string    `json:"config_json,omitempty"`
	UpdatesAccepted  int        `json:"updates_accepted"`
	UpdatesRejected  int        `json:"updates_rejected"`
}

// Store wraps a pgxpool for orchestration queries.
type Store struct {
	pool *pgxpool.Pool
}

// New creates a Store backed by the given connection pool.
func New(pool *pgxpool.Pool) *Store {
	return &Store{pool: pool}
}

// ConnectPool creates a pgx connection pool from a DSN.
func ConnectPool(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("parse dsn: %w", err)
	}
	cfg.MaxConns = 10
	cfg.MinConns = 2

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("create pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping: %w", err)
	}
	return pool, nil
}

// InsertRound records a new round in the rounds audit table.
func (s *Store) InsertRound(ctx context.Context, roundID, modelVersion, state string, config map[string]interface{}) error {
	var configJSON *string
	if config != nil {
		data, err := json.Marshal(config)
		if err != nil {
			return fmt.Errorf("marshal config: %w", err)
		}
		str := string(data)
		configJSON = &str
	}

	_, err := s.pool.Exec(ctx, `
		INSERT INTO rounds (round_id, model_version, state, config_json)
		VALUES ($1, $2, $3, $4)`,
		roundID, modelVersion, state, configJSON,
	)
	if err != nil {
		return fmt.Errorf("insert round: %w", err)
	}
	return nil
}

// UpdateRoundState updates the state and optionally sets closed_at.
func (s *Store) UpdateRoundState(ctx context.Context, roundID, state string) error {
	var err error
	if state == "CLOSED" || state == "DONE" || state == "FAILED" {
		_, err = s.pool.Exec(ctx, `
			UPDATE rounds SET state = $2, closed_at = now() WHERE round_id = $1`,
			roundID, state)
	} else {
		_, err = s.pool.Exec(ctx, `
			UPDATE rounds SET state = $2 WHERE round_id = $1`,
			roundID, state)
	}
	if err != nil {
		return fmt.Errorf("update round state: %w", err)
	}
	return nil
}

// ListRecentRounds returns the last N rounds ordered by started_at desc.
func (s *Store) ListRecentRounds(ctx context.Context, limit int) ([]Round, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT round_id, model_version, started_at, closed_at,
		       state, config_json, updates_accepted, updates_rejected
		FROM rounds
		ORDER BY started_at DESC
		LIMIT $1`, limit)
	if err != nil {
		return nil, fmt.Errorf("list rounds: %w", err)
	}
	defer rows.Close()

	var rounds []Round
	for rows.Next() {
		var r Round
		if err := rows.Scan(
			&r.RoundID, &r.ModelVersion, &r.StartedAt, &r.ClosedAt,
			&r.State, &r.ConfigJSON, &r.UpdatesAccepted, &r.UpdatesRejected,
		); err != nil {
			return nil, fmt.Errorf("scan round: %w", err)
		}
		rounds = append(rounds, r)
	}
	return rounds, rows.Err()
}

// GetRound fetches a single round by ID.
func (s *Store) GetRound(ctx context.Context, roundID string) (*Round, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT round_id, model_version, started_at, closed_at,
		       state, config_json, updates_accepted, updates_rejected
		FROM rounds WHERE round_id = $1`, roundID)

	r := &Round{}
	err := row.Scan(
		&r.RoundID, &r.ModelVersion, &r.StartedAt, &r.ClosedAt,
		&r.State, &r.ConfigJSON, &r.UpdatesAccepted, &r.UpdatesRejected,
	)
	if err == pgx.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get round: %w", err)
	}
	return r, nil
}

// Ping checks the database connection.
func (s *Store) Ping(ctx context.Context) error {
	return s.pool.Ping(ctx)
}
