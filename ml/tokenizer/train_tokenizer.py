"""
ml/tokenizer/train_tokenizer.py

Downloads the Wikipedia Simple English subset (~200 MB) and trains a
SentencePiece BPE model with vocab_size=8192.

Outputs:
    ml/tokenizer/vocab_8192.model   — SentencePiece binary model
    ml/tokenizer/vocab_8192.vocab   — JSON mapping {token: id}

Usage:
    .venv/bin/python ml/tokenizer/train_tokenizer.py
    # Override vocab size:
    VOCAB_SIZE=4096 .venv/bin/python ml/tokenizer/train_tokenizer.py
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import sentencepiece as spm
from datasets import load_dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
VOCAB_SIZE = int(os.environ.get("VOCAB_SIZE", "8192"))
CHARACTER_COVERAGE = 0.9995
MODEL_TYPE = "bpe"
OUTPUT_DIR = Path(__file__).resolve().parent
MODEL_PREFIX = f"vocab_{VOCAB_SIZE}"

# Special tokens — SentencePiece reserves id 0-2 by default (unk, bos, eos).
# We define PAD=0, UNK=1, BOS=2, EOS=3, SPACE=4 via control symbols.
SPECIAL_TOKENS = {
    "[PAD]": 0,
    "[UNK]": 1,
    "[BOS]": 2,
    "[EOS]": 3,
    "[SPACE]": 4,
}


def download_corpus() -> str:
    """Download Simple English Wikipedia and write to a temp text file."""
    log.info("Downloading Wikipedia Simple English dataset...")
    # wikimedia/wikipedia is the maintained Parquet-based version (no loading script).
    ds = load_dataset(
        "wikimedia/wikipedia", "20231101.simple", split="train",
    )

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="wiki_simple_"
    )
    log.info("Writing %d articles to %s ...", len(ds), tmp.name)
    for i, row in enumerate(ds):
        text = row["text"].strip()
        if text:
            tmp.write(text + "\n")
        if (i + 1) % 50_000 == 0:
            log.info("  %d / %d articles written", i + 1, len(ds))
    tmp.close()
    log.info("Corpus written: %s", tmp.name)
    return tmp.name


def train(corpus_path: str) -> None:
    """Train SentencePiece BPE model on the given text corpus."""
    model_path = str(OUTPUT_DIR / MODEL_PREFIX)
    log.info(
        "Training SentencePiece BPE: vocab_size=%d, coverage=%.4f",
        VOCAB_SIZE,
        CHARACTER_COVERAGE,
    )

    # SentencePiece trainer args
    # --pad_id=0, --unk_id=1, --bos_id=2, --eos_id=3 maps our special tokens.
    # --user_defined_symbols adds [SPACE] as id 4 (first user-defined symbol).
    spm.SentencePieceTrainer.train(
        input=corpus_path,
        model_prefix=model_path,
        vocab_size=VOCAB_SIZE,
        character_coverage=CHARACTER_COVERAGE,
        model_type=MODEL_TYPE,
        pad_id=0,
        pad_piece="[PAD]",
        unk_id=1,
        unk_piece="[UNK]",
        bos_id=2,
        bos_piece="[BOS]",
        eos_id=3,
        eos_piece="[EOS]",
        user_defined_symbols=["[SPACE]"],
        num_threads=os.cpu_count() or 4,
        train_extremely_large_corpus=False,
    )

    log.info("SentencePiece model saved: %s.model", model_path)

    # Export JSON vocab: {token_string: token_id}
    sp = spm.SentencePieceProcessor(model_file=f"{model_path}.model")
    vocab = {}
    for i in range(sp.get_piece_size()):
        vocab[sp.id_to_piece(i)] = i

    vocab_json_path = OUTPUT_DIR / f"{MODEL_PREFIX}.vocab"
    with open(vocab_json_path, "w") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    log.info("JSON vocab saved: %s (%d entries)", vocab_json_path, len(vocab))


def main() -> None:
    corpus_path = download_corpus()
    try:
        train(corpus_path)
    finally:
        # Clean up temp corpus file
        try:
            os.unlink(corpus_path)
            log.info("Cleaned up temp corpus: %s", corpus_path)
        except OSError:
            pass

    log.info("Done. Outputs in %s/", OUTPUT_DIR)


if __name__ == "__main__":
    main()
