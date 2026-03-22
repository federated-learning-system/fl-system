"""
ml/training/seed_redis.py

Seeds initial model metadata into Redis after Phase 2 warm-start training.

Writes:
  - model:current           → "v0"
  - model:version:v0        → Hash with model metadata

Usage:
    # From repo root, after Phase 2 training completes:
    .venv/bin/python ml/training/seed_redis.py

    # Override defaults via env:
    REDIS_HOST=localhost REDIS_PORT=6379 \
    MODEL_VERSION=v0 \
    ONNX_S3_KEY=models/v0/model.onnx \
    WEIGHTS_S3_KEY=models/v0/weights.pt \
    .venv/bin/python ml/training/seed_redis.py
"""

import os
import time
import sys
import logging

import redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [seed_redis] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ── Config from environment ───────────────────────────────────────────────────
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))

MODEL_VERSION = os.environ.get("MODEL_VERSION", "v0")
ROUND_ID = os.environ.get("ROUND_ID", "seed")
NUM_CLIENTS = os.environ.get("NUM_CLIENTS", "0")
ACCURACY = os.environ.get("ACCURACY", "0.0")
LOSS = os.environ.get("LOSS", "0.0")
ONNX_S3_KEY = os.environ.get("ONNX_S3_KEY", f"models/{MODEL_VERSION}/model.onnx")
WEIGHTS_S3_KEY = os.environ.get("WEIGHTS_S3_KEY", f"models/{MODEL_VERSION}/weights.pt")

# ── Helpers ───────────────────────────────────────────────────────────────────

def connect(retries: int = 5, delay: float = 2.0) -> redis.Redis:
    """Return a connected Redis client, retrying on failure."""
    for attempt in range(1, retries + 1):
        try:
            client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            client.ping()
            log.info("Connected to Redis at %s:%d", REDIS_HOST, REDIS_PORT)
            return client
        except redis.exceptions.ConnectionError as exc:
            log.warning(
                "Redis not ready (attempt %d/%d): %s", attempt, retries, exc
            )
            if attempt < retries:
                time.sleep(delay)
    log.error("Could not connect to Redis after %d attempts — aborting.", retries)
    sys.exit(1)


def seed(r: redis.Redis) -> None:
    """Write initial model metadata. Skips if model:current already set."""
    existing = r.get("model:current")
    if existing:
        log.info(
            "model:current already set to '%s' — nothing to do. "
            "Pass MODEL_VERSION env var to seed a different version.",
            existing,
        )
        return

    now = str(int(time.time()))
    version_key = f"model:version:{MODEL_VERSION}"

    pipe = r.pipeline(transaction=True)

    # model:version:<ver> hash
    pipe.hset(
        version_key,
        mapping={
            "version": MODEL_VERSION,
            "created_at": now,
            "round_id": ROUND_ID,
            "num_clients": NUM_CLIENTS,
            "accuracy": ACCURACY,
            "loss": LOSS,
            "onnx_s3_key": ONNX_S3_KEY,
            "weights_s3_key": WEIGHTS_S3_KEY,
        },
    )

    # model:current pointer
    pipe.set("model:current", MODEL_VERSION)

    pipe.execute()

    log.info("Seeded model:current = %s", MODEL_VERSION)
    log.info("Seeded %s:", version_key)
    for field, value in r.hgetall(version_key).items():
        log.info("  %-20s = %s", field, value)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    r = connect()
    seed(r)
    log.info("Done.")


if __name__ == "__main__":
    main()
