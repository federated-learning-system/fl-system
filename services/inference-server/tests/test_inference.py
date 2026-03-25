"""
services/inference-server/tests/test_inference.py

Integration tests for the ONNX Inference Server.

Usage:
    # Start the inference server first, then:
    python services/inference-server/tests/test_inference.py

Prerequisites:
    - inference-server running on localhost:8086 (or PORT env)
    - Redis accessible on localhost:6379
    - MinIO accessible with model seeded
"""

from __future__ import annotations

import os
import statistics
import time

import httpx

BASE = os.environ.get("INFERENCE_URL", "http://localhost:8086")


def test_health():
    """Test 1: Health check."""
    resp = httpx.get(f"{BASE}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "model_version" in data
    print(f"Serving model: {data['model_version']}")


def test_inference_3_suggestions():
    """Test 2: Inference returns 3 suggestions."""
    resp = httpx.post(f"{BASE}/infer", json={
        "token_ids": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
        "top_k": 3,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["suggestions"]) == 3, \
        f"expected 3 suggestions, got {len(data['suggestions'])}"
    assert len(data["scores"]) == 3
    assert all(isinstance(s, str) for s in data["suggestions"])
    assert all(isinstance(sc, float) for sc in data["scores"])
    print(f"Suggestions: {data['suggestions']}")
    print(f"Scores: {data['scores']}")


def test_latency_p95():
    """Test 3: Latency — p95 < 100ms."""
    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        httpx.post(f"{BASE}/infer", json={
            "token_ids": [100] * 10,
            "top_k": 3,
        })
        latencies.append((time.perf_counter() - t0) * 1000)

    p95 = sorted(latencies)[47]  # index 47 = 95th percentile of 50
    avg = statistics.mean(latencies)
    print(f"Inference p95 latency: {p95:.1f}ms (avg: {avg:.1f}ms)")
    assert p95 < 100, f"inference too slow: p95={p95:.1f}ms"


def test_short_context():
    """Test 4: Short context padded correctly."""
    resp = httpx.post(f"{BASE}/infer", json={
        "token_ids": [42],
        "top_k": 1,
    })
    assert resp.status_code == 200, \
        f"short context should be handled, got {resp.status_code}"
    data = resp.json()
    assert len(data["suggestions"]) == 1
    print(f"Short context suggestion: {data['suggestions']}")


def test_reload():
    """Test 5: Reload endpoint."""
    resp = httpx.post(f"{BASE}/reload")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    print(f"Reload OK: {data['model_version']}")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_health()
    print("[PASS] Health check")

    test_inference_3_suggestions()
    print("[PASS] Inference returns 3 suggestions")

    test_latency_p95()
    print("[PASS] Latency p95 < 100ms")

    test_short_context()
    print("[PASS] Short context handled")

    test_reload()
    print("[PASS] Reload endpoint")

    print("\nALL INFERENCE SERVER TESTS PASSED")
