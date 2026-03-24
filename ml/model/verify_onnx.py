"""
ml/model/verify_onnx.py

Verifies ONNX export matches PyTorch output and measures inference latency.

Tests:
  1. Max absolute diff between PyTorch and ONNX INT8 < 2.0
  2. Top-1 prediction matches
  3. ONNX p95 inference latency < 50ms on CPU

Usage:
    .venv/bin/python ml/model/verify_onnx.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from ml.model.lstm_model import NextWordLSTM
from ml.model.model_config import ModelConfig

MODEL_DIR = Path(__file__).resolve().parent
CHECKPOINT = _REPO_ROOT / "ml" / "training" / "warmstart_final.pt"
ONNX_FP32 = MODEL_DIR / "model.onnx"
ONNX_INT8 = MODEL_DIR / "model_quant.onnx"


def main() -> None:
    # Load PyTorch model
    checkpoint = torch.load(CHECKPOINT, map_location="cpu", weights_only=False)
    if "model_config" in checkpoint:
        config = ModelConfig.from_dict(checkpoint["model_config"])
    else:
        config = ModelConfig()

    pt_model = NextWordLSTM.from_config(config)
    pt_model.load_state_dict(checkpoint["model_state_dict"])
    pt_model.eval()

    # Load ONNX models
    assert ONNX_FP32.exists(), f"Float32 ONNX not found: {ONNX_FP32}"
    assert ONNX_INT8.exists(), f"INT8 ONNX not found: {ONNX_INT8}"

    sess_fp32 = ort.InferenceSession(str(ONNX_FP32))
    sess_int8 = ort.InferenceSession(str(ONNX_INT8))

    # Prepare inputs
    x = torch.randint(0, config.vocab_size, (1, config.seq_len))
    h0 = np.zeros((config.num_layers, 1, config.hidden_size), dtype=np.float32)
    c0 = np.zeros((config.num_layers, 1, config.hidden_size), dtype=np.float32)
    feed = {
        "token_ids": x.numpy().astype(np.int64),
        "hidden_h": h0,
        "hidden_c": c0,
    }

    # PyTorch inference
    with torch.no_grad():
        pt_logits, _ = pt_model(x)
    pt_np = pt_logits.numpy()

    # ONNX float32 inference
    fp32_logits = sess_fp32.run(["logits"], feed)[0]

    # ONNX INT8 inference
    int8_logits = sess_int8.run(["logits"], feed)[0]

    # Test 1a: Float32 ONNX should match PyTorch exactly (or very close)
    fp32_diff = np.abs(pt_np - fp32_logits).max()
    print(f"Max diff (PyTorch vs ONNX float32): {fp32_diff:.6f}")
    assert fp32_diff < 1e-4, f"Float32 ONNX diverges: {fp32_diff}"
    print("[PASS] Float32 ONNX matches PyTorch")

    # Test 1b: INT8 ONNX within tolerance
    int8_diff = np.abs(pt_np - int8_logits).max()
    print(f"Max diff (PyTorch vs ONNX INT8): {int8_diff:.4f}")
    assert int8_diff < 2.0, f"ONNX INT8 output diverges too much: {int8_diff}"
    print("[PASS] INT8 ONNX within tolerance")

    # Test 2: Top-1 prediction match
    pt_top1 = pt_np.argmax()
    fp32_top1 = fp32_logits.argmax()
    int8_top1 = int8_logits.argmax()
    print(f"Top-1: PyTorch={pt_top1}, FP32={fp32_top1}, INT8={int8_top1}")
    assert pt_top1 == fp32_top1, "Top-1 mismatch: PyTorch vs FP32 ONNX"
    assert pt_top1 == int8_top1, "Top-1 mismatch: PyTorch vs INT8 ONNX"
    print("[PASS] Top-1 predictions match across all three")

    # Test 3: Inference latency (INT8)
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        sess_int8.run(["logits"], feed)
        times.append((time.perf_counter() - t0) * 1000)
    p50 = sorted(times)[25]
    p95 = sorted(times)[int(len(times) * 0.95)]
    print(f"ONNX INT8 latency: p50={p50:.1f}ms, p95={p95:.1f}ms")
    assert p95 < 50, f"ONNX inference too slow: p95={p95}ms"
    print("[PASS] p95 latency < 50ms")

    # File sizes
    fp32_mb = ONNX_FP32.stat().st_size / (1024 * 1024)
    int8_mb = ONNX_INT8.stat().st_size / (1024 * 1024)
    print(f"\nFile sizes: float32={fp32_mb:.1f}MB, INT8={int8_mb:.1f}MB, "
          f"compression={fp32_mb / int8_mb:.1f}x")

    print("\nALL ONNX EXPORT TESTS PASSED")


if __name__ == "__main__":
    main()
