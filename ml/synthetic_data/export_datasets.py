"""
ml/synthetic_data/export_datasets.py

Generates datasets for all 5 client profiles and saves as JSON.

Outputs: data/client-tech.json, data/client-casual.json, etc.
Logs summary stats: token count, unique tokens, top-10 tokens per profile.

Usage:
    .venv/bin/python ml/synthetic_data/export_datasets.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from ml.synthetic_data.generator import CLIENT_PROFILES, generate_client_dataset
from ml.tokenizer.tokenizer import FLTokenizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

TOKENIZER_MODEL = _REPO_ROOT / "ml" / "tokenizer" / "vocab_8192.model"
DATA_DIR = _REPO_ROOT / "data"


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    tokenizer = FLTokenizer(str(TOKENIZER_MODEL))
    log.info("Tokenizer loaded: vocab_size=%d", tokenizer.vocab_size())

    for profile in CLIENT_PROFILES:
        log.info("Generating dataset for %s ...", profile.client_id)
        data = generate_client_dataset(profile, tokenizer)

        # Save JSON
        out_path = DATA_DIR / f"{profile.client_id}.json"
        with open(out_path, "w") as f:
            json.dump(data, f)
        log.info("  Saved %s (%d events)", out_path, len(data))

        # Summary stats
        all_tokens = [e["token_id"] for e in data]
        unique = len(set(all_tokens))
        counter = Counter(all_tokens)
        top10 = counter.most_common(10)
        top10_str = ", ".join(
            f"{tokenizer.decode_single(tid)}({tid}):{cnt}"
            for tid, cnt in top10
        )
        log.info(
            "  %s: %d events, %d unique tokens, top-10: [%s]",
            profile.client_id, len(data), unique, top10_str,
        )

    log.info("All datasets exported to %s/", DATA_DIR)


if __name__ == "__main__":
    main()
