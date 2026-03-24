"""
services/orchestration/tests/test_orchestration.py

Integration tests for the Orchestration Controller.

Usage:
    # Start the orchestration service first, then:
    cd services/orchestration/tests
    python test_orchestration.py

Prerequisites:
    - orchestration service running on localhost:8084
    - aggregation-server running on localhost:50052 with mTLS
    - PostgreSQL accessible (port-forwarded or local)
    - client-registry running (optional — orchestration handles it gracefully)
"""

from __future__ import annotations

import sys
import time

import httpx

BASE = "http://localhost:8084"


def test_start_round():
    """Test 1: Manual round start."""
    resp = httpx.post(f"{BASE}/rounds/start", timeout=10)
    assert resp.status_code in [200, 202], f"Start failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "round_id" in data, f"no round_id in response: {data}"
    round_id = data["round_id"]
    print(f"Started round: {round_id}")
    return round_id


def test_current_round(expected_round_id: str):
    """Test 2: Get current round."""
    time.sleep(1)
    resp = httpx.get(f"{BASE}/rounds/current", timeout=5)
    assert resp.status_code == 200, f"Current failed: {resp.status_code}"
    current = resp.json()
    assert current["round_id"] == expected_round_id, \
        f"round_id mismatch: {current['round_id']} != {expected_round_id}"
    assert current["state"] in ["OPEN", "COLLECTING"], \
        f"unexpected state: {current['state']}"
    print(f"Current state: {current['state']}")


def test_history():
    """Test 3: Round history."""
    resp = httpx.get(f"{BASE}/rounds/history", timeout=5)
    assert resp.status_code == 200, f"History failed: {resp.status_code}"
    history = resp.json()
    assert len(history) >= 1, f"expected at least 1 round in history, got {len(history)}"
    print(f"History: {len(history)} rounds")


def test_health():
    """Test 4: Health endpoint."""
    resp = httpx.get(f"{BASE}/health", timeout=5)
    assert resp.status_code == 200, f"Health failed: {resp.status_code}"
    print("Health: OK")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    round_id = test_start_round()
    print("[PASS] StartRound")

    test_current_round(round_id)
    print("[PASS] CurrentRound")

    test_history()
    print("[PASS] History")

    test_health()
    print("[PASS] Health")

    print("\nALL ORCHESTRATION TESTS PASSED")
