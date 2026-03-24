"""
ml/model/test_model.py

Unit tests for NextWordLSTM forward pass shapes, gradient flow, and config.

Usage:
    .venv/bin/python ml/model/test_model.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import torch

# Allow imports from repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from ml.model.lstm_model import NextWordLSTM
from ml.model.model_config import ModelConfig


def main() -> None:
    model = NextWordLSTM()

    # Test 1: Parameter count
    # embed(8192*128) + LSTM_L1(4*(128*256+256*256+2*256)) + LSTM_L2(4*(256*256+256*256+2*256))
    # + linear(256*8192+8192) ≈ 4.08M
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Parameters: {n_params:,}")
    assert 3_000_000 < n_params < 6_000_000, f"unexpected param count: {n_params}"
    print("[PASS] Parameter count in range (3M, 6M)")

    # Test 2: Forward pass shape
    batch, seq_len = 4, 10
    x = torch.randint(0, 8192, (batch, seq_len))
    logits, hidden = model(x)
    assert logits.shape == (batch, 8192), f"wrong output shape: {logits.shape}"
    assert len(hidden) == 2  # (h_n, c_n) for LSTM
    h_n, c_n = hidden
    assert h_n.shape == (2, batch, 256), f"wrong h_n shape: {h_n.shape}"
    assert c_n.shape == (2, batch, 256), f"wrong c_n shape: {c_n.shape}"
    print(f"[PASS] Forward pass: input {x.shape} -> logits {logits.shape}, hidden h_n={h_n.shape}")

    # Test 3: Gradient flows
    loss = logits.sum()
    loss.backward()
    for name, param in model.named_parameters():
        assert param.grad is not None, f"no gradient for {name}"
    print("[PASS] Gradients flow to all parameters")

    # Test 4: Inference mode (no hidden state)
    model.eval()
    with torch.no_grad():
        logits2, _ = model(x)
        assert logits2.shape == (batch, 8192)
    print("[PASS] Inference mode works")

    # Test 5: Hidden state continuity (autoregressive generation)
    model.eval()
    with torch.no_grad():
        x1 = torch.randint(0, 8192, (1, 10))
        logits_a, hidden_a = model(x1)
        x2 = torch.randint(0, 8192, (1, 10))
        logits_b, hidden_b = model(x2, hidden_a)
        assert logits_b.shape == (1, 8192)
        # hidden state should have changed
        assert not torch.equal(hidden_a[0], hidden_b[0])
    print("[PASS] Hidden state continuity across steps")

    # Test 6: ModelConfig serialization round-trip
    cfg = ModelConfig()
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
        cfg.to_json(f.name)
        cfg2 = ModelConfig.from_json(f.name)
    assert cfg.to_dict() == cfg2.to_dict(), "config round-trip mismatch"
    print("[PASS] ModelConfig JSON round-trip")

    # Test 7: from_config factory
    cfg3 = ModelConfig(embed_dim=64, hidden_size=128)
    model3 = NextWordLSTM.from_config(cfg3)
    assert model3.embed_dim == 64
    assert model3.hidden_size == 128
    print("[PASS] NextWordLSTM.from_config()")

    print(f"\nALL MODEL TESTS PASSED  ({n_params:,} parameters)")


if __name__ == "__main__":
    main()
