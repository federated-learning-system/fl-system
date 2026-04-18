"""
ml/tokenizer/export_vocab_browser.py

Exports the SentencePiece BPE model to a browser-friendly JSON format
that includes piece scores needed for unigram-style tokenization.

Output: frontend/keyboard-ui/public/vocab/vocab_8192.json
Format:
{
  "vocab": {"piece": id, ...},
  "scores": [score_for_id_0, score_for_id_1, ...],
  "vocab_size": 8192
}

Usage:
    .venv/bin/python ml/tokenizer/export_vocab_browser.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import sentencepiece as spm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "vocab_8192.model"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "keyboard-ui" / "public" / "vocab"


def main() -> None:
    sp = spm.SentencePieceProcessor(model_file=str(MODEL_PATH))
    size = sp.get_piece_size()
    log.info("Loaded SentencePiece model: %d pieces", size)

    vocab: dict[str, int] = {}
    scores: list[float] = []
    reverse: list[str] = [""] * size

    for i in range(size):
        piece = sp.id_to_piece(i)
        score = sp.get_score(i)
        vocab[piece] = i
        scores.append(round(score, 6))
        reverse[i] = piece

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "vocab_8192.json"

    data = {
        "vocab": vocab,
        "scores": scores,
        "reverse": reverse,
        "vocab_size": size,
    }

    with open(out_path, "w") as f:
        json.dump(data, f, ensure_ascii=False)

    size_kb = out_path.stat().st_size / 1024
    log.info("Exported: %s (%.1f KB)", out_path, size_kb)


if __name__ == "__main__":
    main()
