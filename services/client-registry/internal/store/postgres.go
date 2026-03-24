package store

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Client mirrors the clients table in PostgreSQL.
type Client struct {
	ClientID            string    `json:"client_id"`
	DeviceClass         string    `json:"device_class"`
	RegisteredAt        time.Time `json:"registered_at"`
	LastSeen            *time.Time `json:"last_seen,omitempty"`
	CertFingerprint     *string   `json:"cert_fingerprint,omitempty"`
	RamMB               *int      `json:"ram_mb,omitempty"`
	HasGPU              bool      `json:"has_gpu"`
	CPUCores            *int      `json:"cpu_cores,omitempty"`
	OS                  *string   `json:"os,omitempty"`
	CanTrain            bool      `json:"can_train"`
	VocabSizeCap        int       `json:"vocab_size_cap"`
	DPEpsilonCumulative float64   `json:"dp_epsilon_cumulative"`
	DPMaxEpsilon        float64   `json:"dp_max_epsilon"`
	IsActive            bool      `json:"is_active"`
}

// Capabilities matches the JSON payload for device capabilities.
type Capabilities struct {
	RamMB        *int    `json:"ram_mb,omitempty"`
	HasGPU       *bool   `json:"has_gpu,omitempty"`
	CPUCores     *int    `json:"cpu_cores,omitempty"`
	OS           *string `json:"os,omitempty"`
	CanTrain     *bool   `json:"can_train,omitempty"`
	VocabSizeCap *int    `json:"vocab_size_cap,omitempty"`
}

// Store wraps a pgxpool for client-registry queries.
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

// InsertClient registers a new client and returns the full row.
func (s *Store) InsertClient(ctx context.Context, clientID, deviceClass string, caps Capabilities) (*Client, error) {
	hasGPU := false
	if caps.HasGPU != nil {
		hasGPU = *caps.HasGPU
	}
	canTrain := true
	if caps.CanTrain != nil {
		canTrain = *caps.CanTrain
	}
	vocabSizeCap := 8192
	if caps.VocabSizeCap != nil {
		vocabSizeCap = *caps.VocabSizeCap
	}

	now := time.Now()
	_, err := s.pool.Exec(ctx, `
		INSERT INTO clients (client_id, device_class, registered_at, last_seen,
		                     ram_mb, has_gpu, cpu_cores, os, can_train, vocab_size_cap)
		VALUES ($1, $2, $3, $3, $4, $5, $6, $7, $8, $9)`,
		clientID, deviceClass, now,
		caps.RamMB, hasGPU, caps.CPUCores, caps.OS, canTrain, vocabSizeCap,
	)
	if err != nil {
		return nil, fmt.Errorf("insert client: %w", err)
	}

	return s.GetClient(ctx, clientID)
}

// GetClient fetches a single client by ID.
func (s *Store) GetClient(ctx context.Context, clientID string) (*Client, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT client_id, device_class, registered_at, last_seen,
		       cert_fingerprint, ram_mb, has_gpu, cpu_cores, os,
		       can_train, vocab_size_cap, dp_epsilon_cumulative,
		       dp_max_epsilon, is_active
		FROM clients WHERE client_id = $1`, clientID)

	c := &Client{}
	err := row.Scan(
		&c.ClientID, &c.DeviceClass, &c.RegisteredAt, &c.LastSeen,
		&c.CertFingerprint, &c.RamMB, &c.HasGPU, &c.CPUCores, &c.OS,
		&c.CanTrain, &c.VocabSizeCap, &c.DPEpsilonCumulative,
		&c.DPMaxEpsilon, &c.IsActive,
	)
	if err == pgx.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get client: %w", err)
	}
	return c, nil
}

// UpdateHeartbeat sets last_seen to now for the given client.
func (s *Store) UpdateHeartbeat(ctx context.Context, clientID string) error {
	tag, err := s.pool.Exec(ctx,
		`UPDATE clients SET last_seen = now() WHERE client_id = $1`, clientID)
	if err != nil {
		return fmt.Errorf("update heartbeat: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("client not found: %s", clientID)
	}
	return nil
}

// ListEligible returns active clients seen in the last 10 minutes with remaining DP budget.
func (s *Store) ListEligible(ctx context.Context) ([]Client, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT client_id, device_class, registered_at, last_seen,
		       cert_fingerprint, ram_mb, has_gpu, cpu_cores, os,
		       can_train, vocab_size_cap, dp_epsilon_cumulative,
		       dp_max_epsilon, is_active
		FROM clients
		WHERE is_active = true
		  AND last_seen > now() - interval '10 minutes'
		  AND dp_epsilon_cumulative < dp_max_epsilon`)
	if err != nil {
		return nil, fmt.Errorf("list eligible: %w", err)
	}
	defer rows.Close()

	var clients []Client
	for rows.Next() {
		var c Client
		if err := rows.Scan(
			&c.ClientID, &c.DeviceClass, &c.RegisteredAt, &c.LastSeen,
			&c.CertFingerprint, &c.RamMB, &c.HasGPU, &c.CPUCores, &c.OS,
			&c.CanTrain, &c.VocabSizeCap, &c.DPEpsilonCumulative,
			&c.DPMaxEpsilon, &c.IsActive,
		); err != nil {
			return nil, fmt.Errorf("scan eligible: %w", err)
		}
		clients = append(clients, c)
	}
	return clients, rows.Err()
}

// UpdateBudget adds epsilon_spent to the cumulative DP budget for a client.
func (s *Store) UpdateBudget(ctx context.Context, clientID string, epsilonSpent float64) error {
	tag, err := s.pool.Exec(ctx, `
		UPDATE clients
		SET dp_epsilon_cumulative = dp_epsilon_cumulative + $2
		WHERE client_id = $1`,
		clientID, epsilonSpent)
	if err != nil {
		return fmt.Errorf("update budget: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("client not found: %s", clientID)
	}
	return nil
}

// Ping checks the database connection.
func (s *Store) Ping(ctx context.Context) error {
	return s.pool.Ping(ctx)
}
