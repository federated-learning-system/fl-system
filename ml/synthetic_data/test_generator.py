"""
ml/synthetic_data/test_generator.py

Tests for synthetic data generation: sizes, token ranges, non-IID properties.

Usage:
    .venv/bin/python ml/synthetic_data/test_generator.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from ml.synthetic_data.generator import CLIENT_PROFILES, generate_client_dataset
from ml.tokenizer.tokenizer import FLTokenizer

TOKENIZER_MODEL = _REPO_ROOT / "ml" / "tokenizer" / "vocab_8192.model"


def main() -> None:
    t = FLTokenizer(str(TOKENIZER_MODEL))

    datasets = {}
    for profile in CLIENT_PROFILES:
        data = generate_client_dataset(profile, t)
        datasets[profile.client_id] = data
        unique = len(set(e["token_id"] for e in data))
        print(f"{profile.client_id}: {len(data)} events, unique tokens: {unique}")

    # Test 1: Dataset sizes match profiles
    for profile in CLIENT_PROFILES:
        assert len(datasets[profile.client_id]) == profile.dataset_size, \
            f"wrong dataset size for {profile.client_id}"
    print("[PASS] Dataset sizes match profiles")

    # Test 2: All token IDs in valid range
    for cid, data in datasets.items():
        for event in data:
            assert 0 <= event["token_id"] < 8192, f"invalid token_id in {cid}"
            assert len(event["context_ids"]) == 10, f"wrong context length in {cid}"
            for tid in event["context_ids"]:
                assert 0 <= tid < 8192, f"invalid context token_id in {cid}"
    print("[PASS] All token IDs in valid range [0, 8192)")

    # Test 3: Non-IID verification — tech and medical should have different top tokens
    tech_tokens = [e["token_id"] for e in datasets["client-tech"]]
    medical_tokens = [e["token_id"] for e in datasets["client-medical"]]
    tech_top10 = set(
        sorted(set(tech_tokens), key=tech_tokens.count, reverse=True)[:10]
    )
    medical_top10 = set(
        sorted(set(medical_tokens), key=medical_tokens.count, reverse=True)[:10]
    )
    overlap = len(tech_top10 & medical_top10)
    print(f"Top-10 token overlap (tech vs medical): {overlap}/10")
    assert overlap < 8, f"datasets too similar (non-IID not working): overlap={overlap}"
    print("[PASS] Non-IID verified — tech vs medical top-10 overlap < 8")

    # Test 4: Non-IID — sports vs casual
    sports_tokens = [e["token_id"] for e in datasets["client-sports"]]
    casual_tokens = [e["token_id"] for e in datasets["client-casual"]]
    sports_top10 = set(
        sorted(set(sports_tokens), key=sports_tokens.count, reverse=True)[:10]
    )
    casual_top10 = set(
        sorted(set(casual_tokens), key=casual_tokens.count, reverse=True)[:10]
    )
    overlap2 = len(sports_top10 & casual_top10)
    print(f"Top-10 token overlap (sports vs casual): {overlap2}/10")
    assert overlap2 < 8, f"datasets too similar: overlap={overlap2}"
    print("[PASS] Non-IID verified — sports vs casual")

    # Test 5: Timestamps are monotonically increasing
    for cid, data in datasets.items():
        timestamps = [e["timestamp_ms"] for e in data]
        assert timestamps == sorted(timestamps), f"timestamps not sorted in {cid}"
    print("[PASS] Timestamps monotonically increasing")

    # Test 6: Deterministic with same seed (via client_id hash)
    data_a = generate_client_dataset(CLIENT_PROFILES[0], t)
    data_b = generate_client_dataset(CLIENT_PROFILES[0], t)
    assert data_a[0]["token_id"] == data_b[0]["token_id"], "not deterministic"
    print("[PASS] Deterministic generation")

    print("\nALL SYNTHETIC DATA TESTS PASSED")


if __name__ == "__main__":
    main()
