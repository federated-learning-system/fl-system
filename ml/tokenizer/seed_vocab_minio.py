"""
ml/tokenizer/seed_vocab_minio.py

Uploads the trained vocab files to MinIO at fl-models/vocab/.

Usage:
    # Requires MinIO to be reachable (port-forward or in-cluster)
    MINIO_ENDPOINT=http://localhost:9000 .venv/bin/python ml/tokenizer/seed_vocab_minio.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Add repo root to path so we can import services.shared
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from services.shared.minio_client import BUCKET_MODELS, get_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

TOKENIZER_DIR = Path(__file__).resolve().parent
VOCAB_SIZE = int(os.environ.get("VOCAB_SIZE", "8192"))


def seed() -> None:
    model_file = TOKENIZER_DIR / f"vocab_{VOCAB_SIZE}.model"
    vocab_file = TOKENIZER_DIR / f"vocab_{VOCAB_SIZE}.vocab"

    if not model_file.exists():
        log.error("Model file not found: %s — run train_tokenizer.py first", model_file)
        sys.exit(1)

    s3 = get_client()

    for local_path in [model_file, vocab_file]:
        if not local_path.exists():
            log.warning("Skipping missing file: %s", local_path)
            continue
        key = f"vocab/{local_path.name}"
        s3.upload_file(str(local_path), BUCKET_MODELS, key)
        log.info("Uploaded %s → s3://%s/%s", local_path.name, BUCKET_MODELS, key)

    log.info("Vocab seed complete.")


if __name__ == "__main__":
    seed()
