"""
services/fedavg-engine/tests/test_aggregator.py

Unit tests for the FedAvg-R aggregation function.

Usage:
    cd /path/to/fls
    .venv/bin/python services/fedavg-engine/tests/test_aggregator.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolve repo root and fedavg-engine directory for imports
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_ENGINE_DIR))

import torch
from aggregator import fedavg_r, serialize_delta, load_update_blob


def test_weighted_average():
    """Test 1: Weighted average is computed correctly."""
    base_model = {"output.weight": torch.zeros(8192, 256)}

    updates = [
        {"delta": {"output.weight": torch.full((8192, 256), 0.1)},
         "num_samples": 100, "is_straggler": False, "checksum": "ok"},
        {"delta": {"output.weight": torch.full((8192, 256), -0.1)},
         "num_samples": 200, "is_straggler": False, "checksum": "ok"},
        {"delta": {"output.weight": torch.full((8192, 256), 0.3)},
         "num_samples": 300, "is_straggler": False, "checksum": "ok"},
    ]

    new_model = fedavg_r(updates, base_model, config={"penalty_factor": 0.5})
    result = new_model["output.weight"][0, 0].item()
    # (100*0.1 + 200*(-0.1) + 300*0.3) / (100+200+300) = 80/600
    expected = (100 * 0.1 + 200 * (-0.1) + 300 * 0.3) / 600
    print(f"Aggregated value: {result:.6f}, expected: {expected:.6f}")
    assert abs(result - expected) < 1e-4, f"aggregation wrong: {result} != {expected}"


def test_straggler_penalty():
    """Test 2: Straggler penalty reduces effective weight."""
    base_model = {"output.weight": torch.zeros(8192, 256)}

    updates = [
        {"delta": {"output.weight": torch.full((8192, 256), 0.1)},
         "num_samples": 100, "is_straggler": False, "checksum": "ok"},
        {"delta": {"output.weight": torch.full((8192, 256), -0.1)},
         "num_samples": 200, "is_straggler": False, "checksum": "ok"},
        {"delta": {"output.weight": torch.full((8192, 256), 0.3)},
         "num_samples": 300, "is_straggler": True, "checksum": "ok"},
    ]

    new_model = fedavg_r(updates, base_model, config={"penalty_factor": 0.5})
    result = new_model["output.weight"][0, 0].item()
    # client-3 effective weight = 300 * 0.5 = 150
    # (100*0.1 + 200*(-0.1) + 150*0.3) / (100+200+150) = 35/450
    expected = (100 * 0.1 + 200 * (-0.1) + 150 * 0.3) / 450
    print(f"With penalty: {result:.6f}, expected: {expected:.6f}")
    assert abs(result - expected) < 1e-4, "straggler penalty not applied correctly"


def test_min_clients():
    """Test 3: Raise ValueError with too few updates."""
    base_model = {"output.weight": torch.zeros(8192, 256)}
    updates = [
        {"delta": {"output.weight": torch.full((8192, 256), 0.1)},
         "num_samples": 100, "is_straggler": False, "checksum": "ok"},
    ]

    try:
        fedavg_r(updates, base_model, config={"min_clients": 2, "penalty_factor": 0.5})
        assert False, "should raise with only 1 update when min_clients=2"
    except ValueError as e:
        print(f"Correctly raised ValueError: {e}")


def test_serialize_roundtrip():
    """Test 4: Serialize/deserialize delta roundtrip."""
    delta = {"weight": torch.randn(128, 64)}
    blob = serialize_delta(delta)
    restored = load_update_blob(blob, checksum="ok")
    assert torch.allclose(delta["weight"], restored["weight"]), \
        "roundtrip failed"
    print(f"Serialize roundtrip OK (blob size: {len(blob)} bytes)")


def test_multi_param_aggregation():
    """Test 5: Aggregation works across multiple parameters."""
    base_model = {
        "embedding.weight": torch.zeros(100, 32),
        "lstm.weight_ih": torch.zeros(128, 32),
        "output.bias": torch.zeros(100),
    }

    updates = [
        {"delta": {
            "embedding.weight": torch.full((100, 32), 1.0),
            "lstm.weight_ih": torch.full((128, 32), 2.0),
            "output.bias": torch.full((100,), 0.5),
         }, "num_samples": 50, "is_straggler": False, "checksum": "ok"},
        {"delta": {
            "embedding.weight": torch.full((100, 32), 3.0),
            "lstm.weight_ih": torch.full((128, 32), 0.0),
            "output.bias": torch.full((100,), 1.5),
         }, "num_samples": 50, "is_straggler": False, "checksum": "ok"},
    ]

    new_model = fedavg_r(updates, base_model, config={"penalty_factor": 0.5})

    # Equal weights (50/50) → simple average of deltas
    assert abs(new_model["embedding.weight"][0, 0].item() - 2.0) < 1e-4
    assert abs(new_model["lstm.weight_ih"][0, 0].item() - 1.0) < 1e-4
    assert abs(new_model["output.bias"][0].item() - 1.0) < 1e-4
    print("Multi-param aggregation OK")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_weighted_average()
    print("[PASS] Weighted average")

    test_straggler_penalty()
    print("[PASS] Straggler penalty")

    test_min_clients()
    print("[PASS] Minimum clients check")

    test_serialize_roundtrip()
    print("[PASS] Serialize roundtrip")

    test_multi_param_aggregation()
    print("[PASS] Multi-param aggregation")

    print("\nALL FEDAVG-R TESTS PASSED")
