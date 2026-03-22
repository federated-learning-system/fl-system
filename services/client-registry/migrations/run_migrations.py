"""
services/client-registry/migrations/run_migrations.py

Applies SQL migration files in order against the fl_registry database.
Idempotent — safe to run on every service start.  Each migration is guarded
by a version check in the schema_migrations table so it executes at most once.

Usage (standalone):
    PGHOST=localhost PGPORT=5432 python run_migrations.py

Usage (from service startup):
    from services.client_registry.migrations.run_migrations import apply_migrations
    apply_migrations()

Environment variables:
    PGHOST      default: postgresql        (k8s service name)
    PGPORT      default: 5432
    PGUSER      default: postgres
    PGPASSWORD  default: flpg123
    PGDATABASE  default: fl_registry
"""

from __future__ import annotations

import logging
import os
import sys
import time
from glob import glob
from pathlib import Path

import psycopg2  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_PGHOST = os.environ.get("PGHOST", "postgresql")
_PGPORT = int(os.environ.get("PGPORT", "5432"))
_PGUSER = os.environ.get("PGUSER", "postgres")
_PGPASSWORD = os.environ.get("PGPASSWORD", "flpg123")
_PGDATABASE = os.environ.get("PGDATABASE", "fl_registry")

MIGRATIONS_DIR = Path(__file__).resolve().parent


# ── Connection with retry ─────────────────────────────────────────────────────

def _connect(max_retries: int = 8) -> psycopg2.extensions.connection:
    """Connect to PostgreSQL with exponential backoff."""
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            conn = psycopg2.connect(
                host=_PGHOST,
                port=_PGPORT,
                user=_PGUSER,
                password=_PGPASSWORD,
                dbname=_PGDATABASE,
            )
            conn.autocommit = True
            log.info("Connected to PostgreSQL at %s:%s/%s", _PGHOST, _PGPORT, _PGDATABASE)
            return conn
        except psycopg2.OperationalError as exc:
            if attempt == max_retries:
                raise
            log.warning(
                "PostgreSQL not ready (attempt %d/%d): %s — retrying in %.0fs",
                attempt, max_retries, exc, delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError("unreachable")


# ── Migration runner ──────────────────────────────────────────────────────────

def apply_migrations() -> list[str]:
    """
    Scan the migrations directory for ``*.sql`` files and execute them in
    sorted order.  Each file is responsible for its own idempotency via
    the ``schema_migrations`` table (see 001_init.sql for the pattern).

    Returns the list of migration files that were executed.
    """
    sql_files = sorted(glob(str(MIGRATIONS_DIR / "*.sql")))
    if not sql_files:
        log.info("No migration files found in %s", MIGRATIONS_DIR)
        return []

    conn = _connect()
    applied: list[str] = []
    try:
        cur = conn.cursor()
        for fpath in sql_files:
            fname = os.path.basename(fpath)
            log.info("Applying migration: %s", fname)
            with open(fpath) as f:
                sql = f.read()
            cur.execute(sql)
            applied.append(fname)
            log.info("  %s — done", fname)
        cur.close()
    finally:
        conn.close()

    log.info("All migrations applied: %s", applied)
    return applied


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        applied = apply_migrations()
        print(f"Applied {len(applied)} migration(s): {applied}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
