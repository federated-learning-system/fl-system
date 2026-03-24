"""
ml/dp_engine/test_dp.py

Tests for the DPEngine: clipping, noise injection, and privacy accounting.

Usage:
    .venv/bin/python ml/dp_engine/test_dp.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import torch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from ml.dp_engine.dp_engine import DPEngine


def main() -> None:
    dp = DPEngine(clip_norm=1.0, noise_multiplier=1.1, target_epsilon=1.0, target_delta=1e-5)

    # Test 1: Clipping — large gradient should be clipped to clip_norm
    delta = {"layer": torch.randn(256, 256) * 100}  # huge gradient
    clipped = dp.clip_and_noise(delta, num_samples=100)
    clipped_norm = torch.norm(clipped["layer"]).item()
    print(f"Clipped+noised norm: {clipped_norm:.4f}")
    assert clipped_norm < 50, f"gradient too large after clipping: {clipped_norm}"
    print("[PASS] Clipping works — large gradient bounded")

    # Test 2: Zero gradient stays near zero after clipping (noise dominates)
    dp2 = DPEngine(clip_norm=1.0, noise_multiplier=1.1, target_epsilon=1.0, target_delta=1e-5)
    zero_delta = {"layer": torch.zeros(256, 256)}
    noised = dp2.clip_and_noise(zero_delta, num_samples=100)
    noise_norm = torch.norm(noised["layer"]).item()
    print(f"Noise norm for zero input: {noise_norm:.4f}")
    assert noise_norm > 0, "DP engine should add noise"
    print("[PASS] Noise injected into zero gradient")

    # Test 3: Privacy accounting
    dp3 = DPEngine(clip_norm=1.0, noise_multiplier=1.1, target_epsilon=1.0, target_delta=1e-5)
    epsilon_spent = dp3.compute_epsilon(num_samples=500, num_steps=1)
    print(f"Epsilon for 1 round, 500 samples: {epsilon_spent:.4f}")
    assert 0 < epsilon_spent <= 2.0, f"unexpected epsilon: {epsilon_spent}"
    print("[PASS] Privacy accounting returns valid epsilon")

    # Test 4: Budget tracking
    dp4 = DPEngine(clip_norm=1.0, noise_multiplier=1.1, target_epsilon=1.0, target_delta=1e-5)
    initial_budget = dp4.budget_remaining()
    print(f"Initial budget: {initial_budget:.4f}")
    dp4.clip_and_noise({"layer": torch.randn(10)}, num_samples=100)
    remaining = dp4.budget_remaining()
    print(f"Budget after 1 round: {remaining:.4f}")
    assert remaining < initial_budget, "budget should decrease after use"
    print("[PASS] Budget decreases after clip_and_noise")

    # Test 5: Budget exhaustion detection
    dp5 = DPEngine(clip_norm=1.0, noise_multiplier=1.1, target_epsilon=0.001, target_delta=1e-5)
    dp5.clip_and_noise({"layer": torch.randn(10)}, num_samples=10)
    assert dp5.is_budget_exhausted(), "budget should be exhausted with tiny epsilon"
    print("[PASS] Budget exhaustion detected")

    # Test 6: Multi-layer delta
    dp6 = DPEngine(clip_norm=1.0, noise_multiplier=1.1, target_epsilon=1.0, target_delta=1e-5)
    multi_delta = {
        "embedding.weight": torch.randn(8192, 128) * 10,
        "lstm.weight_ih_l0": torch.randn(1024, 128) * 10,
        "output.weight": torch.randn(8192, 256) * 10,
    }
    noised_multi = dp6.clip_and_noise(multi_delta, num_samples=100)
    assert set(noised_multi.keys()) == set(multi_delta.keys())
    for name in multi_delta:
        assert noised_multi[name].shape == multi_delta[name].shape
    print("[PASS] Multi-layer delta processed correctly")

    print("\nALL DP ENGINE TESTS PASSED")


if __name__ == "__main__":
    main()
