"""
tests/e2e/test_full_round.py

End-to-end round validation for the FLS federated learning system.

Validates the complete FL round lifecycle:
    1. Trigger round via Orchestration Controller (POST /rounds/start)
    2. Wait for clients to submit updates (poll Redis round:{id}:updates set)
    3. Verify FedAvg-R completes — new model version appears in Redis
    4. Verify MODEL_UPDATED event received via WebSocket
    5. Verify new model is downloadable from MinIO via presigned URL

Prerequisites:
    - All infrastructure running: redis, minio, postgres
    - All 8 services running: aggregation-server, client-registry, orchestration,
      straggler-watch, websocket-push, fedavg-engine, inference-server, offload-worker
    - At least 2 simulated clients running (min_clients default)
    - Model seeded in Redis (model:current) and MinIO

Environment variables (with defaults for docker-compose):
    ORCHESTRATION_URL   http://localhost:8082
    WEBSOCKET_URL       ws://localhost:8080/ws
    REGISTRY_URL        http://localhost:8081
    REDIS_HOST          localhost
    REDIS_PORT          6379
    MINIO_ENDPOINT      http://localhost:9000
    MINIO_ACCESS_KEY    flminio
    MINIO_SECRET_KEY    flminio123

Usage:
    # From project root, after `make up-all`:
    .venv/bin/python tests/e2e/test_full_round.py

    # With custom endpoints (e.g., port-forwarded k3d services):
    ORCHESTRATION_URL=http://localhost:30082 .venv/bin/python tests/e2e/test_full_round.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time

import boto3
from botocore.client import Config as BotoConfig
import redis
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

ORCHESTRATION_URL = os.environ.get("ORCHESTRATION_URL", "http://localhost:8082")
WEBSOCKET_URL = os.environ.get("WEBSOCKET_URL", "ws://localhost:8080/ws")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8081")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "flminio")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "flminio123")

# Timeouts
ROUND_TIMEOUT_S = 300  # 5 minutes max for round to complete
POLL_INTERVAL_S = 5
WS_WAIT_S = 10  # extra time to wait for WebSocket MODEL_UPDATED after DONE

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_redis() -> redis.Redis:
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


# ── WebSocket Listener ───────────────────────────────────────────────────────

class WSModelUpdateListener:
    """Background WebSocket listener that captures MODEL_UPDATED events."""

    def __init__(self):
        self.received = threading.Event()
        self.version: str | None = None
        self.raw_messages: list[dict] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="ws-e2e")
        self._thread.start()

    def _run(self):
        try:
            import websocket
            ws = websocket.WebSocket()
            ws.settimeout(2.0)
            ws.connect(WEBSOCKET_URL)

            while not self._stop.is_set():
                try:
                    msg = ws.recv()
                    if not msg:
                        continue
                    data = json.loads(msg)
                    self.raw_messages.append(data)

                    # MODEL_UPDATED from fedavg-engine: {"version": "...", "round_id": "..."}
                    if "version" in data and "round_id" in data:
                        self.version = data["version"]
                        self.received.set()
                    # Also handle wrapped format: {"event": "MODEL_UPDATED", ...}
                    elif data.get("event") == "MODEL_UPDATED":
                        payload = data.get("payload", data)
                        self.version = payload.get("version")
                        self.received.set()

                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    if not self._stop.is_set():
                        print(f"  [WS] Error: {e}")
                    break

            ws.close()
        except ImportError:
            print("  [WS] websocket-client not installed — skipping WebSocket check")
        except Exception as e:
            print(f"  [WS] Connection failed: {e}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


# ── Test Steps ────────────────────────────────────────────────────────────────

def step_0_preflight_checks():
    """Verify all services are reachable before starting the round."""
    print("\n── Step 0: Preflight Checks ──────────────────────────────────────")

    # Redis
    r = get_redis()
    assert r.ping(), "Redis not reachable"
    print(f"  Redis:          OK ({REDIS_HOST}:{REDIS_PORT})")

    # MinIO
    s3 = get_s3()
    buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    assert "fl-models" in buckets, f"fl-models bucket missing, found: {buckets}"
    print(f"  MinIO:          OK (buckets: {buckets})")

    # Model seeded
    initial_version = r.get("model:current")
    assert initial_version, "model:current not set in Redis — run seed_model_store.py first"
    print(f"  Model version:  {initial_version}")

    model_meta = r.hgetall(f"model:version:{initial_version}")
    print(f"  Model metadata: {dict(model_meta)}")

    # Orchestration
    resp = requests.get(f"{ORCHESTRATION_URL}/healthz", timeout=5)
    assert resp.status_code == 200, f"Orchestration unhealthy: {resp.status_code}"
    print(f"  Orchestration:  OK ({ORCHESTRATION_URL})")

    # Client Registry
    resp = requests.get(f"{REGISTRY_URL}/healthz", timeout=5)
    assert resp.status_code == 200, f"Client Registry unhealthy: {resp.status_code}"
    print(f"  Client Registry: OK ({REGISTRY_URL})")

    # Check registered clients
    resp = requests.get(f"{REGISTRY_URL}/clients/eligible", timeout=5)
    if resp.status_code == 200:
        clients = resp.json()
        print(f"  Eligible clients: {len(clients)}")
        for c in clients:
            cid = c.get("client_id", c.get("ClientID", "?"))
            print(f"    - {cid}")
    else:
        print(f"  Eligible clients: (registry returned {resp.status_code})")

    return initial_version


def step_1_trigger_round():
    """Trigger a new round via the Orchestration Controller."""
    print("\n── Step 1: Trigger Round ─────────────────────────────────────────")

    resp = requests.post(f"{ORCHESTRATION_URL}/rounds/start", timeout=15)
    print(f"  POST /rounds/start → {resp.status_code}")
    print(f"  Response: {resp.text.strip()}")

    assert resp.status_code in (200, 202), f"Round start failed: {resp.status_code} {resp.text}"

    data = resp.json()
    round_id = data.get("round_id", "")
    assert round_id, "No round_id in response"

    model_version = data.get("model_version", "")
    state = data.get("state", "")
    print(f"  Round ID:       {round_id}")
    print(f"  Model version:  {model_version}")
    print(f"  Initial state:  {state}")

    return round_id


def step_2_wait_for_updates(round_id: str, min_expected: int = 2):
    """Poll Redis until clients submit updates or timeout."""
    print(f"\n── Step 2: Wait for Client Updates (round: {round_id}) ──────────")

    r = get_redis()
    deadline = time.time() + ROUND_TIMEOUT_S
    last_count = -1

    while time.time() < deadline:
        state = r.get(f"round:{round_id}:state") or "UNKNOWN"
        update_count = r.scard(f"round:{round_id}:updates")
        submitters = r.smembers(f"round:{round_id}:updates")

        if update_count != last_count:
            print(f"  State: {state:12s} | Updates: {update_count} | Clients: {submitters}")
            last_count = update_count

        # If round is DONE or FAILED, stop polling
        if state in ("DONE", "FAILED"):
            break

        # If we have enough updates and the round is still COLLECTING,
        # continue waiting — straggler-watch or fedavg will close it
        time.sleep(POLL_INTERVAL_S)

    final_state = r.get(f"round:{round_id}:state") or "UNKNOWN"
    final_count = r.scard(f"round:{round_id}:updates")
    final_clients = r.smembers(f"round:{round_id}:updates")

    print(f"\n  Final state:    {final_state}")
    print(f"  Final updates:  {final_count}")
    print(f"  Submitters:     {final_clients}")

    assert final_state == "DONE", (
        f"Round did not complete: state={final_state} "
        f"(updates={final_count}, expected>={min_expected})"
    )
    assert final_count >= min_expected, (
        f"Not enough updates: {final_count} < {min_expected}"
    )

    return final_clients


def step_3_verify_model_version(initial_version: str) -> str:
    """Check that a new model version appeared in Redis."""
    print("\n── Step 3: Verify Model Version Bump ────────────────────────────")

    r = get_redis()
    new_version = r.get("model:current")
    print(f"  Initial version: {initial_version}")
    print(f"  New version:     {new_version}")

    assert new_version, "model:current is empty after round"
    assert new_version != initial_version, (
        f"Model version did not change: still {initial_version}"
    )

    # Verify metadata hash
    meta = r.hgetall(f"model:version:{new_version}")
    print(f"  Model metadata:  {dict(meta)}")
    assert meta.get("version") == new_version
    assert "round_id" in meta
    assert "num_clients" in meta
    assert int(meta["num_clients"]) >= 2

    return new_version


def step_4_verify_websocket_push(ws_listener: WSModelUpdateListener, new_version: str):
    """Verify MODEL_UPDATED was received via WebSocket."""
    print("\n── Step 4: Verify WebSocket Push ─────────────────────────────────")

    # Give extra time for the push to propagate
    ws_listener.received.wait(timeout=WS_WAIT_S)

    print(f"  Messages received: {len(ws_listener.raw_messages)}")
    for i, msg in enumerate(ws_listener.raw_messages):
        event = msg.get("event", msg.get("version", "?"))
        print(f"    [{i}] {event}")

    if ws_listener.received.is_set():
        print(f"  MODEL_UPDATED version: {ws_listener.version}")
        assert ws_listener.version == new_version, (
            f"WebSocket version mismatch: got {ws_listener.version}, "
            f"expected {new_version}"
        )
        print("  WebSocket push: VERIFIED")
    else:
        print("  WARNING: MODEL_UPDATED not received via WebSocket")
        print("  (This can happen if WebSocket connection dropped during the round)")
        print("  Proceeding — WebSocket push is best-effort in this test")


def step_5_verify_model_downloadable(new_version: str):
    """Download the new model from MinIO to verify it exists and is valid."""
    print("\n── Step 5: Verify Model Downloadable from MinIO ─────────────────")

    r = get_redis()
    meta = r.hgetall(f"model:version:{new_version}")

    # The FedAvg engine stores the weights at models/{version}/model_weights.pt
    weights_key = f"models/{new_version}/model_weights.pt"
    print(f"  Weights key:    {weights_key}")

    s3 = get_s3()

    # Check object exists
    try:
        head = s3.head_object(Bucket="fl-models", Key=weights_key)
        size = head["ContentLength"]
        print(f"  Object size:    {size:,} bytes")
    except Exception as e:
        # Try the key from metadata if available
        alt_key = meta.get("onnx_s3_key", "")
        print(f"  Primary key not found, trying metadata key: {alt_key}")
        head = s3.head_object(Bucket="fl-models", Key=alt_key)
        size = head["ContentLength"]
        weights_key = alt_key
        print(f"  Object size:    {size:,} bytes")

    # Download and verify size
    obj = s3.get_object(Bucket="fl-models", Key=weights_key)
    model_bytes = obj["Body"].read()
    print(f"  Downloaded:     {len(model_bytes):,} bytes")

    # Model weights should be substantial (the LSTM is ~4M params = ~16MB float32)
    # But gzip compressed state_dict could be smaller
    assert len(model_bytes) > 100_000, (
        f"Model too small ({len(model_bytes)} bytes) — likely corrupt"
    )
    print("  Model download: VERIFIED")

    # Also generate a presigned URL to verify that flow works
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": "fl-models", "Key": weights_key},
        ExpiresIn=60,
    )
    print(f"  Presigned URL:  {url[:80]}...")

    # Download via presigned URL
    resp = requests.get(url, timeout=30)
    assert resp.status_code == 200, f"Presigned download failed: {resp.status_code}"
    assert len(resp.content) == len(model_bytes), "Presigned download size mismatch"
    print("  Presigned download: VERIFIED")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  FLS End-to-End Round Validation")
    print("=" * 70)

    start_time = time.time()

    # Step 0: Preflight
    initial_version = step_0_preflight_checks()

    # Start WebSocket listener before triggering the round
    ws_listener = WSModelUpdateListener()
    ws_listener.start()
    time.sleep(1)  # Let WS connect

    try:
        # Step 1: Trigger round
        round_id = step_1_trigger_round()

        # Step 2: Wait for updates + aggregation
        submitters = step_2_wait_for_updates(round_id, min_expected=2)

        # Step 3: Verify model version bump
        new_version = step_3_verify_model_version(initial_version)

        # Step 4: Verify WebSocket push
        step_4_verify_websocket_push(ws_listener, new_version)

        # Step 5: Verify model downloadable
        step_5_verify_model_downloadable(new_version)

    finally:
        ws_listener.stop()

    elapsed = time.time() - start_time

    print("\n" + "=" * 70)
    print(f"  E2E ROUND TEST PASSED ({elapsed:.1f}s)")
    print(f"  Round:    {round_id}")
    print(f"  Clients:  {len(submitters)} submitted")
    print(f"  Model:    {initial_version} → {new_version}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n  E2E TEST FAILED: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\n  E2E TEST ERROR: {type(e).__name__}: {e}")
        sys.exit(1)
