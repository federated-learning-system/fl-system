"""
ml/tokenizer/tokenizer.py

Wrapper around a trained SentencePiece BPE model for the FLS system.

Usage:
    from ml.tokenizer.tokenizer import FLTokenizer

    tok = FLTokenizer("ml/tokenizer/vocab_8192.model")
    ids = tok.encode("hello world")
    text = tok.decode(ids)
"""

from __future__ import annotations

from pathlib import Path

import sentencepiece as spm


class FLTokenizer:
    """Thin wrapper around a SentencePiece model for FLS next-word prediction."""

    # Special token IDs (must match train_tokenizer.py)
    PAD_ID = 0
    UNK_ID = 1
    BOS_ID = 2
    EOS_ID = 3
    SPACE_ID = 4  # [SPACE] user-defined symbol

    def __init__(self, model_path: str | Path) -> None:
        self._sp = spm.SentencePieceProcessor(model_file=str(model_path))

    def encode(self, text: str) -> list[int]:
        """Encode text to a list of token IDs."""
        return self._sp.encode(text, out_type=int)

    def decode(self, ids: list[int]) -> str:
        """Decode a list of token IDs back to text."""
        return self._sp.decode(ids)

    def decode_single(self, id: int) -> str:
        """Decode a single token ID to its string piece."""
        return self._sp.id_to_piece(id)

    def vocab_size(self) -> int:
        """Return the vocabulary size (8192 by default)."""
        return self._sp.get_piece_size()

    def piece_to_id(self, piece: str) -> int:
        """Return the ID for a given token piece string."""
        return self._sp.piece_to_id(piece)

    def id_to_piece(self, id: int) -> str:
        """Return the piece string for a given token ID."""
        return self._sp.id_to_piece(id)
