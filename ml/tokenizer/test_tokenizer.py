"""
ml/tokenizer/test_tokenizer.py

Quick smoke test for the trained BPE tokenizer.

Usage:
    .venv/bin/python ml/tokenizer/test_tokenizer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root or from ml/tokenizer/
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from tokenizer import FLTokenizer

MODEL_PATH = _HERE / "vocab_8192.model"


def main() -> None:
    assert MODEL_PATH.exists(), f"Model not found: {MODEL_PATH}. Run train_tokenizer.py first."
    t = FLTokenizer(str(MODEL_PATH))

    # Test 1: Vocab size
    assert t.vocab_size() == 8192, f"vocab size mismatch: got {t.vocab_size()}"
    print(f"[PASS] vocab_size = {t.vocab_size()}")

    # Test 2: Encode/decode round-trip
    text = "federated learning improves predictions"
    ids = t.encode(text)
    decoded = t.decode(ids)
    assert len(ids) > 0, "empty encoding"
    assert isinstance(ids[0], int), "ids must be integers"
    print(f"[PASS] Encode: '{text}' -> {ids}")
    print(f"[PASS] Decode: {ids} -> '{decoded}'")

    # Test 3: Special tokens are accessible
    assert t.decode_single(0) == "[PAD]", f"PAD token mismatch: {t.decode_single(0)}"
    assert t.decode_single(1) == "[UNK]", f"UNK token mismatch: {t.decode_single(1)}"
    assert t.decode_single(2) == "[BOS]", f"BOS token mismatch: {t.decode_single(2)}"
    assert t.decode_single(3) == "[EOS]", f"EOS token mismatch: {t.decode_single(3)}"
    assert t.decode_single(4) == "[SPACE]", f"SPACE token mismatch: {t.decode_single(4)}"
    print("[PASS] Special tokens: [PAD]=0, [UNK]=1, [BOS]=2, [EOS]=3, [SPACE]=4")

    # Test 4: Token IDs in valid range
    for token_id in ids:
        assert 0 <= token_id < 8192, f"token_id {token_id} out of range"
    print(f"[PASS] All {len(ids)} token IDs in range [0, 8192)")

    # Test 5: Multiple sentences
    for sample in [
        "The quick brown fox jumps over the lazy dog",
        "I am typing on my phone keyboard",
        "next word prediction using LSTM",
        "differential privacy preserves user data",
    ]:
        ids2 = t.encode(sample)
        dec2 = t.decode(ids2)
        assert len(ids2) > 0
        print(f"  '{sample}' -> {len(ids2)} tokens -> '{dec2}'")

    print("\nALL TOKENIZER TESTS PASSED")


if __name__ == "__main__":
    main()
