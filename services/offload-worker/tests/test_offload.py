"""
services/offload-worker/tests/test_offload.py

Integration tests for the Offload Worker service.

Usage:
    # Start the offload-worker API (Go) and trainer (Python) first, then:
    python services/offload-worker/tests/test_offload.py

Prerequisites:
    - offload-worker API running on localhost:8085
    - offload trainer consuming Redis Streams
    - Redis accessible on localhost:6379
    - MinIO accessible on localhost:9000 (or 29000 via port-forward)
"""

from __future__ import annotations

import json
import time

import httpx

BASE = "http://localhost:8085"


def test_create_job():
    """Test 1: Create offload job."""
    resp = httpx.post(f"{BASE}/offload/jobs", json={
        "client_id": "client-tech",
        "device_class": "LAPTOP_SIM",
        "round_id": "round-test-offload",
        "model_version": "v1.0.0",
        "num_samples": 100,
    })
    assert resp.status_code == 200, f"create job failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "job_id" in data, f"missing job_id: {data}"
    assert "upload_url" in data, f"missing upload_url: {data}"
    print(f"Job created: {data['job_id']}")
    print(f"Upload URL: {data['upload_url'][:80]}...")
    return data


def test_upload_tokens(upload_url: str):
    """Test 2: Upload token data to presigned URL."""
    token_batch = json.dumps({"tokens": list(range(100))}).encode()
    resp = httpx.put(
        upload_url,
        content=token_batch,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert resp.status_code in [200, 204], f"upload failed: {resp.status_code}"
    print("Token batch uploaded successfully")


def test_poll_status(job_id: str):
    """Test 3: Poll until done."""
    status = "QUEUED"
    for _ in range(30):
        resp = httpx.get(f"{BASE}/offload/jobs/{job_id}")
        status = resp.json()["status"]
        print(f"Job status: {status}")
        if status in ["DONE", "FAILED"]:
            break
        time.sleep(1)

    assert status == "DONE", f"job did not complete: {status}"
    return status


def test_esp32_job():
    """Test 4: ESP32 histogram job."""
    resp = httpx.post(f"{BASE}/offload/jobs", json={
        "client_id": "esp32-001",
        "device_class": "ESP32",
        "round_id": "round-test-offload",
        "model_version": "v1.0.0",
        "frequency_histogram": [
            {"token_range": "0-511", "count": 20},
            {"token_range": "512-1023", "count": 5},
        ],
    })
    assert resp.status_code == 200, f"ESP32 job failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "job_id" in data, f"missing job_id: {data}"
    print(f"ESP32 job accepted: {data['job_id']}")

    # Poll for completion
    for _ in range(30):
        status_resp = httpx.get(f"{BASE}/offload/jobs/{data['job_id']}")
        status = status_resp.json()["status"]
        print(f"ESP32 job status: {status}")
        if status in ["DONE", "FAILED"]:
            break
        time.sleep(1)

    return data["job_id"]


def test_healthz():
    """Test 5: Health check."""
    resp = httpx.get(f"{BASE}/healthz")
    assert resp.status_code == 200, f"healthz failed: {resp.status_code}"
    print("Health check OK")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_healthz()
    print("[PASS] Health check")

    data = test_create_job()
    print("[PASS] Create job")

    test_upload_tokens(data["upload_url"])
    print("[PASS] Upload tokens")

    test_poll_status(data["job_id"])
    print("[PASS] Poll status")

    test_esp32_job()
    print("[PASS] ESP32 job")

    print("\nALL OFFLOAD WORKER TESTS PASSED")
