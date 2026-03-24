"""
services/client-registry/tests/test_registry.py

Integration tests for the FL Client Registry REST API.

Usage:
    # Start the service first (port-forwarded or local):
    #   DB_HOST=localhost .venv/bin/python -m pytest services/client-registry/tests/test_registry.py
    # Or standalone:
    #   python services/client-registry/tests/test_registry.py

Prerequisites:
    - client-registry running on localhost:8083
    - PostgreSQL with 001_init.sql migration applied
"""

from __future__ import annotations

import os
import httpx

BASE = os.environ.get("REGISTRY_URL", "http://localhost:8083")


def test_register():
    resp = httpx.post(f"{BASE}/clients/register", json={
        "device_class": "LAPTOP_SIM",
        "caps": {"ram_mb": 400, "has_gpu": False, "cpu_cores": 1,
                 "os": "linux", "can_train": True, "vocab_size_cap": 8192}
    })
    assert resp.status_code == 200, f"register failed: {resp.text}"
    data = resp.json()
    assert "client_id" in data
    assert "jwt_token" in data
    return data["client_id"], data["jwt_token"]


def test_get_client():
    cid, _ = test_register()
    resp = httpx.get(f"{BASE}/clients/{cid}")
    assert resp.status_code == 200, f"get client failed: {resp.text}"
    data = resp.json()
    assert data["client_id"] == cid
    assert data["device_class"] == "LAPTOP_SIM"


def test_heartbeat():
    cid, token = test_register()
    resp = httpx.put(f"{BASE}/clients/{cid}/heartbeat",
                     headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"heartbeat failed: {resp.text}"


def test_eligible_list():
    cid, token = test_register()
    # Send heartbeat first so last_seen is recent
    httpx.put(f"{BASE}/clients/{cid}/heartbeat",
              headers={"Authorization": f"Bearer {token}"})
    resp = httpx.get(f"{BASE}/clients/eligible")
    assert resp.status_code == 200, f"eligible failed: {resp.text}"
    clients = resp.json()
    assert any(c["client_id"] == cid for c in clients), \
        f"client {cid} not in eligible list"


def test_update_budget():
    cid, token = test_register()
    resp = httpx.post(f"{BASE}/clients/{cid}/budget",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"epsilon_spent": 0.5})
    assert resp.status_code == 200, f"budget update failed: {resp.text}"

    # Verify budget was updated
    resp2 = httpx.get(f"{BASE}/clients/{cid}")
    assert resp2.status_code == 200
    assert resp2.json()["dp_epsilon_cumulative"] == 0.5


def test_refresh_token():
    cid, token = test_register()
    resp = httpx.post(f"{BASE}/auth/refresh",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, f"refresh failed: {resp.text}"
    data = resp.json()
    assert data["client_id"] == cid
    assert "jwt_token" in data
    # New token should be different from old one
    assert data["jwt_token"] != token


def test_jwt_required():
    resp = httpx.put(f"{BASE}/clients/fake-id/heartbeat")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}"


def test_jwt_mismatch():
    cid, token = test_register()
    # Use valid token but wrong client_id in path
    resp = httpx.put(f"{BASE}/clients/wrong-id/heartbeat",
                     headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}"


def test_healthz():
    resp = httpx.get(f"{BASE}/healthz")
    assert resp.status_code == 200, f"healthz failed: {resp.text}"


if __name__ == "__main__":
    test_healthz()
    print("[PASS] healthz")

    test_register()
    print("[PASS] register")

    test_get_client()
    print("[PASS] get_client")

    test_heartbeat()
    print("[PASS] heartbeat")

    test_eligible_list()
    print("[PASS] eligible_list")

    test_update_budget()
    print("[PASS] update_budget")

    test_refresh_token()
    print("[PASS] refresh_token")

    test_jwt_required()
    print("[PASS] jwt_required (401)")

    test_jwt_mismatch()
    print("[PASS] jwt_mismatch (403)")

    print("\nALL CLIENT REGISTRY TESTS PASSED")
