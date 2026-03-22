-- 001_init.sql
-- Initial schema for the FL client registry and round audit log.
--
-- Applied automatically by storage-setup.sh (kubectl exec) and
-- idempotently by run_migrations.py on service start.
-- ─────────────────────────────────────────────────────────────────────

-- ── Migration tracking ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(64) PRIMARY KEY,
    applied_at  TIMESTAMPTZ DEFAULT now()
);

-- Guard: skip if this migration was already applied.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = '001_init') THEN
        RAISE NOTICE 'Migration 001_init already applied — skipping.';
        RETURN;
    END IF;

    -- ── Clients ─────────────────────────────────────────────────────
    CREATE TABLE clients (
        client_id             VARCHAR(64)      PRIMARY KEY,
        device_class          VARCHAR(32)      NOT NULL,   -- LAPTOP_SIM | ANDROID | ESP32
        registered_at         TIMESTAMPTZ      DEFAULT now(),
        last_seen             TIMESTAMPTZ,
        cert_fingerprint      VARCHAR(128),
        ram_mb                INT,
        has_gpu               BOOLEAN          DEFAULT FALSE,
        cpu_cores             INT,
        os                    VARCHAR(32),
        can_train             BOOLEAN          DEFAULT TRUE,
        vocab_size_cap        INT              DEFAULT 8192,
        dp_epsilon_cumulative DOUBLE PRECISION DEFAULT 0.0,
        dp_max_epsilon        DOUBLE PRECISION DEFAULT 10.0,
        is_active             BOOLEAN          DEFAULT TRUE
    );

    -- ── Rounds ──────────────────────────────────────────────────────
    CREATE TABLE rounds (
        round_id         VARCHAR(64)  PRIMARY KEY,
        model_version    VARCHAR(32)  NOT NULL,
        started_at       TIMESTAMPTZ  DEFAULT now(),
        closed_at        TIMESTAMPTZ,
        state            VARCHAR(32)  DEFAULT 'OPEN',
        config_json      JSONB,
        updates_accepted INT          DEFAULT 0,
        updates_rejected INT          DEFAULT 0
    );

    -- ── Indexes ─────────────────────────────────────────────────────
    CREATE INDEX idx_clients_device_class ON clients(device_class);
    CREATE INDEX idx_clients_last_seen    ON clients(last_seen);
    CREATE INDEX idx_rounds_state         ON rounds(state);

    -- ── Record migration ────────────────────────────────────────────
    INSERT INTO schema_migrations (version) VALUES ('001_init');

    RAISE NOTICE 'Migration 001_init applied successfully.';
END $$;
