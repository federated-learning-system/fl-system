"""
ml/training/seed_model_store.py

Uploads ONNX models + vocab to MinIO and seeds Redis with model metadata.

Uploads:
    fl-models/models/v1.0.0/model.onnx
    fl-models/models/v1.0.0/model_quant.onnx
    fl-models/vocab/vocab_8192.model
    fl-models/vocab/vocab_8192.vocab

Redis writes:
    model:version:v1.0.0 → hash with version, checksum, blob keys, etc.
    model:current        → "v1.0.0"

Usage:
    # Local (requires Redis + MinIO port-forwards):
    REDIS_HOST=localhost MINIO_ENDPOINT=http://localhost:19000 \
        .venv/bin/python ml/training/seed_model_store.py

    # Override version:
    MODEL_VERSION=v2.0.0 .venv/bin/python ml/training/seed_model_store.py

Environment:
    REDIS_HOST       default: localhost
    MINIO_ENDPOINT   default: http://minio:9000
    MODEL_VERSION    default: v1.0.0
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from services.shared.minio_client import BUCKET_MODELS, get_client as get_s3
from services.shared.redis_client import get_client as get_redis, keys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
MODEL_VERSION = os.environ.get("MODEL_VERSION", "v1.0.0")

# File paths
MODEL_DIR = _REPO_ROOT / "ml" / "model"
TOKENIZER_DIR = _REPO_ROOT / "ml" / "tokenizer"

ONNX_FP32 = MODEL_DIR / "model.onnx"
ONNX_INT8 = MODEL_DIR / "model_quant.onnx"
VOCAB_MODEL = TOKENIZER_DIR / "vocab_8192.model"
VOCAB_JSON = TOKENIZER_DIR / "vocab_8192.vocab"

# Warm-start checkpoint (for sample_count metadata)
WARMSTART_CKPT = _REPO_ROOT / "ml" / "training" / "warmstart_final.pt"


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_to_minio() -> dict[str, str]:
    """Upload all model and vocab files to MinIO. Returns S3 key mapping."""
    s3 = get_s3()
    uploads: dict[str, str] = {}

    files = [
        (ONNX_FP32, f"models/{MODEL_VERSION}/model.onnx"),
        (ONNX_INT8, f"models/{MODEL_VERSION}/model_quant.onnx"),
        (VOCAB_MODEL, "vocab/vocab_8192.model"),
        (VOCAB_JSON, "vocab/vocab_8192.vocab"),
    ]

    for local_path, s3_key in files:
        if not local_path.exists():
            log.warning("Skipping missing file: %s", local_path)
            continue
        s3.upload_file(str(local_path), BUCKET_MODELS, s3_key)
        size_mb = local_path.stat().st_size / (1024 * 1024)
        log.info("Uploaded %s → s3://%s/%s (%.1f MB)", local_path.name, BUCKET_MODELS, s3_key, size_mb)
        uploads[local_path.name] = s3_key

    return uploads


def seed_redis(uploads: dict[str, str]) -> None:
    """Write model metadata to Redis."""
    r = get_redis()

    # Compute checksum of the primary ONNX model
    checksum = sha256_file(ONNX_FP32) if ONNX_FP32.exists() else "unknown"

    # Try to read sample count from warm-start checkpoint
    sample_count = 0
    if WARMSTART_CKPT.exists():
        try:
            import torch
            ckpt = torch.load(WARMSTART_CKPT, map_location="cpu", weights_only=False)
            # The checkpoint doesn't store sample_count directly; estimate from epoch info
            sample_count = ckpt.get("epoch", 0) * 1000  # approximate
        except Exception:
            pass

    version_key = keys.model_version(MODEL_VERSION)
    now = str(int(time.time()))

    mapping = {
        "version": MODEL_VERSION,
        "created_at": now,
        "checksum": checksum,
        "sample_count": str(sample_count),
        "epsilon_sum": "0.0",
        "blob_key": uploads.get("model.onnx", f"models/{MODEL_VERSION}/model.onnx"),
        "quant_blob_key": uploads.get("model_quant.onnx", f"models/{MODEL_VERSION}/model_quant.onnx"),
        "vocab_key": uploads.get("vocab_8192.model", "vocab/vocab_8192.model"),
    }

    pipe = r.pipeline(transaction=True)
    pipe.hset(version_key, mapping=mapping)
    pipe.set(keys.model_current(), MODEL_VERSION)
    pipe.execute()

    log.info("Redis seeded:")
    log.info("  %s = %s", keys.model_current(), MODEL_VERSION)
    log.info("  %s:", version_key)
    for k, v in mapping.items():
        val = v if len(v) < 70 else v[:67] + "..."
        log.info("    %-16s = %s", k, val)


def main() -> None:
    log.info("Seeding model store for version %s", MODEL_VERSION)

    # Upload to MinIO
    uploads = upload_to_minio()

    # Seed Redis
    seed_redis(uploads)

    log.info("Done. model:current = %s", MODEL_VERSION)


if __name__ == "__main__":
    main()
