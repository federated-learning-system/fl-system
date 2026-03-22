"""
services/shared/redis_client.py

Shared Redis connection helper for all FLS Python services.

Features:
  - Reads config from environment variables
  - Exponential back-off retry on startup (container races)
  - Typed key-builder helpers that enforce the schema in redis-schema.md
  - Module-level singleton — call get_client() to obtain the shared instance

Usage:
    from services.shared.redis_client import get_client, keys

    r = get_client()
    r.set(keys.model_current(), "v1")

Environment variables:
    REDIS_HOST       default: localhost
    REDIS_PORT       default: 6379
    REDIS_DB         default: 0
    REDIS_POOL_SIZE  default: 10
    REDIS_RETRY_MAX  default: 8
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import redis
from redis import Redis
from redis.connection import ConnectionPool

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
_REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
_REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
_POOL_SIZE = int(os.environ.get("REDIS_POOL_SIZE", "10"))
_RETRY_MAX = int(os.environ.get("REDIS_RETRY_MAX", "8"))

# Module-level singleton
_pool: Optional[ConnectionPool] = None
_client: Optional[Redis] = None


# ── Connection pool & client ──────────────────────────────────────────────────

def _make_pool() -> ConnectionPool:
    return redis.ConnectionPool(
        host=_REDIS_HOST,
        port=_REDIS_PORT,
        db=_REDIS_DB,
        max_connections=_POOL_SIZE,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def get_client(*, retries: int = _RETRY_MAX) -> Redis:
    """
    Return the module-level Redis client, creating it on first call.

    Retries with exponential back-off so services can start before Redis is
    fully ready (common in Docker Compose / k3d).
    """
    global _pool, _client

    if _client is not None:
        return _client

    if _pool is None:
        _pool = _make_pool()

    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            c = Redis(connection_pool=_pool)
            c.ping()
            _client = c
            log.info(
                "Redis connected: %s:%d db=%d", _REDIS_HOST, _REDIS_PORT, _REDIS_DB
            )
            return _client
        except redis.exceptions.ConnectionError as exc:
            log.warning(
                "Redis not ready (attempt %d/%d, retry in %.1fs): %s",
                attempt,
                retries,
                delay,
                exc,
            )
            if attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 30.0)  # cap at 30 s

    raise RuntimeError(
        f"Cannot connect to Redis at {_REDIS_HOST}:{_REDIS_PORT} "
        f"after {retries} attempts"
    )


def close() -> None:
    """Disconnect the module-level client (useful in tests)."""
    global _pool, _client
    if _client is not None:
        _client.close()
        _client = None
    if _pool is not None:
        _pool.disconnect()
        _pool = None


# ── Key builder — enforces the schema in infra/k8s/redis-schema.md ───────────

class _Keys:
    """
    Centralised key-name factory.  Import `keys` from this module:

        from services.shared.redis_client import keys
        keys.round_state("round-42")   # → "round:round-42:state"
    """

    # ── Model ─────────────────────────────────────────────────────────────────

    @staticmethod
    def model_current() -> str:
        """String key holding the current active model version."""
        return "model:current"

    @staticmethod
    def model_version(version: str) -> str:
        """Hash key for a specific model version's metadata."""
        return f"model:version:{version}"

    # ── Round ─────────────────────────────────────────────────────────────────

    @staticmethod
    def round_state(round_id: str) -> str:
        """String key for round FSM state (OPEN/COLLECTING/…)."""
        return f"round:{round_id}:state"

    @staticmethod
    def round_updates(round_id: str) -> str:
        """Set key of client_ids that have submitted updates this round."""
        return f"round:{round_id}:updates"

    @staticmethod
    def round_config(round_id: str) -> str:
        """Hash key for the round config snapshot."""
        return f"round:{round_id}:config"

    # ── Client ────────────────────────────────────────────────────────────────

    @staticmethod
    def client_budget(client_id: str) -> str:
        """Hash key for a client's cumulative DP budget."""
        return f"client:{client_id}:budget"

    # ── Straggler ─────────────────────────────────────────────────────────────

    @staticmethod
    def straggler_deadline(round_id: str) -> str:
        """
        String key that expires at the round deadline, triggering the
        straggler-watch service via keyspace notifications.
        """
        return f"straggler:{round_id}:deadline"

    # ── Pub/Sub channels ──────────────────────────────────────────────────────

    CHANNEL_ROUND_EVENTS = "fl:round:events"
    CHANNEL_MODEL_UPDATED = "fl:model:updated"


keys = _Keys()
