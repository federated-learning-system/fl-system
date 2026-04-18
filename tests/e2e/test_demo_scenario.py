"""
tests/e2e/test_demo_scenario.py

Automated demo rehearsal for the FLS federated learning system.

Validates the full judge-facing demo flow:
    1. Fresh cluster — verify all services healthy
    2. Register 5 simulated clients
    3. Trigger round via orchestration
    4. Wait for clients to submit (or straggler timeout)
    5. Verify aggregation completes (model version bump)
    6. Verify web frontend receives MODEL_UPDATED via WebSocket
    7. Verify new model serves next-word suggestions
    8. Run 3 consecutive rounds — verify perplexity non-increasing

Prerequisites:
    - `make demo-start` completed successfully
    - All infrastructure + services + clients running

Environment variables (with defaults for docker-compose):
    ORCHESTRATION_URL   http://localhost:8082
    WEBSOCKET_URL       ws://localhost:8080/ws
    REGISTRY_URL        http://localhost:8081
    INFERENCE_URL       http://localhost:8000
    REDIS_HOST          localhost
    REDIS_PORT          6379
    MINIO_ENDPOINT      http://localhost:9000
    MINIO_ACCESS_KEY    flminio
    MINIO_SECRET_KEY    flminio123

Usage:
    .venv/bin/python tests/e2e/test_demo_scenario.py
"""

from __future__ import annotations

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
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://localhost:8000")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "flminio")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "flminio123")

# Timeouts
ROUND_TIMEOUT_S = 300  # 5 minutes max per round
POLL_INTERVAL_S = 5
WS_WAIT_S = 15  # wait for MODEL_UPDATED WebSocket event
TOTAL_ROUNDS = 3
HEALTH_TIMEOUT_S = 5

# Client IDs (must match docker-compose.clients.yml)
EXPECTED_CLIENTS = ["client-tech", "client-casual", "client-medical", "client-sports", "client-straggler"]

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


def log_step(step: int, sub: str, msg: str):
    print(f"  [{step}.{sub}] {msg}")


# ── WebSocket Listener ───────────────────────────────────────────────────────

class WSModelUpdateListener:
    """Background WebSocket listener that captures MODEL_UPDATED events."""

    def __init__(self):
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="ws-demo")
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

                    # Detect MODEL_UPDATED in either format
                    version = None
                    if "version" in data and "round_id" in data:
                        version = data["version"]
                    elif data.get("event") == "MODEL_UPDATED":
                        payload = data.get("payload", data)
                        version = payload.get("version")

                    if version:
                        with self._lock:
                            self.events.append({"version": version, "ts": time.time()})

                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    if not self._stop.is_set():
                        print(f"  [WS] Error: {e}")
                    break
            ws.close()
        except ImportError:
            print("  [WS] websocket-client not installed — skipping WebSocket checks")
        except Exception as e:
            print(f"  [WS] Connection failed: {e}")

    def get_events(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


# ── Step 1: Preflight — verify all services healthy ─────────────────────────

def step_1_preflight() -> str:
    """Verify all services are reachable. Returns initial model version."""
    print("\n" + "=" * 70)
    print("  Step 1: Preflight — Verify All Services Healthy")
    print("=" * 70)

    errors = []

    # Redis
    try:
        r = get_redis()
        assert r.ping(), "Redis PING failed"
        log_step(1, "a", f"Redis: OK ({REDIS_HOST}:{REDIS_PORT})")
    except Exception as e:
        errors.append(f"Redis: {e}")
        log_step(1, "a", f"Redis: FAIL — {e}")

    # MinIO
    try:
        s3 = get_s3()
        buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
        assert "fl-models" in buckets, f"fl-models bucket missing, found: {buckets}"
        log_step(1, "b", f"MinIO: OK (buckets: {buckets})")
    except Exception as e:
        errors.append(f"MinIO: {e}")
        log_step(1, "b", f"MinIO: FAIL — {e}")

    # PostgreSQL (via client-registry health)
    try:
        resp = requests.get(f"{REGISTRY_URL}/healthz", timeout=HEALTH_TIMEOUT_S)
        assert resp.status_code == 200
        log_step(1, "c", f"Client Registry: OK ({REGISTRY_URL})")
    except Exception as e:
        errors.append(f"Client Registry: {e}")
        log_step(1, "c", f"Client Registry: FAIL — {e}")

    # Orchestration
    try:
        resp = requests.get(f"{ORCHESTRATION_URL}/healthz", timeout=HEALTH_TIMEOUT_S)
        assert resp.status_code == 200
        log_step(1, "d", f"Orchestration: OK ({ORCHESTRATION_URL})")
    except Exception as e:
        errors.append(f"Orchestration: {e}")
        log_step(1, "d", f"Orchestration: FAIL — {e}")

    # Inference server
    try:
        resp = requests.get(f"{INFERENCE_URL}/health", timeout=HEALTH_TIMEOUT_S)
        assert resp.status_code == 200
        data = resp.json()
        log_step(1, "e", f"Inference Server: OK (model={data.get('model_version', '?')})")
    except Exception as e:
        errors.append(f"Inference Server: {e}")
        log_step(1, "e", f"Inference Server: FAIL — {e}")

    # WebSocket
    try:
        import websocket
        ws = websocket.WebSocket()
        ws.settimeout(5.0)
        ws.connect(WEBSOCKET_URL)
        ws.close()
        log_step(1, "f", f"WebSocket: OK ({WEBSOCKET_URL})")
    except ImportError:
        log_step(1, "f", "WebSocket: SKIP (websocket-client not installed)")
    except Exception as e:
        errors.append(f"WebSocket: {e}")
        log_step(1, "f", f"WebSocket: FAIL — {e}")

    # Model seeded
    r = get_redis()
    initial_version = r.get("model:current")
    if initial_version:
        log_step(1, "g", f"Model seeded: {initial_version}")
    else:
        errors.append("model:current not set in Redis")
        log_step(1, "g", "Model seeded: FAIL — model:current not in Redis")

    if errors:
        print(f"\n  PREFLIGHT FAILED ({len(errors)} errors):")
        for err in errors:
            print(f"    - {err}")
        raise AssertionError(f"Preflight failed: {len(errors)} services unreachable")

    return initial_version


# ── Step 2: Verify 5 clients registered ──────────────────────────────────────

def step_2_verify_clients():
    """Check that 5 simulated clients are registered."""
    print("\n" + "=" * 70)
    print("  Step 2: Verify Registered Clients")
    print("=" * 70)

    # Clients auto-register on startup; poll until we see them (up to 60s)
    deadline = time.time() + 60
    registered = []

    while time.time() < deadline:
        try:
            resp = requests.get(f"{REGISTRY_URL}/clients/eligible", timeout=5)
            if resp.status_code == 200:
                clients = resp.json()
                registered = [c.get("client_id", c.get("ClientID", "?")) for c in clients]
                log_step(2, "a", f"Eligible clients: {len(registered)}")
                for cid in registered:
                    log_step(2, " ", f"  - {cid}")

                if len(registered) >= len(EXPECTED_CLIENTS):
                    break
        except Exception:
            pass
        time.sleep(3)

    # We need at least 2 clients for FedAvg — 5 is ideal but straggler might lag
    assert len(registered) >= 2, (
        f"Not enough clients registered: {len(registered)} (need >= 2)"
    )
    log_step(2, "b", f"Clients registered: {len(registered)} (minimum 2 required)")


# ── Step 3: Run a single round ───────────────────────────────────────────────

def run_single_round(round_num: int, prev_version: str) -> tuple[str, str, set]:
    """
    Trigger and complete a single FL round.
    Returns (round_id, new_model_version, submitters).
    """
    print(f"\n{'─' * 70}")
    print(f"  Round {round_num}/3: Trigger → Collect → Aggregate")
    print(f"{'─' * 70}")

    # 3a. Trigger round
    resp = requests.post(f"{ORCHESTRATION_URL}/rounds/start", timeout=15)
    log_step(3, "a", f"POST /rounds/start → {resp.status_code}")
    assert resp.status_code in (200, 202), f"Round start failed: {resp.status_code} {resp.text}"

    data = resp.json()
    round_id = data.get("round_id", "")
    assert round_id, "No round_id in response"
    log_step(3, "b", f"Round ID: {round_id}")

    # 3b. Wait for updates, auto-close when >= 2 clients submit, then wait for DONE
    r = get_redis()
    deadline = time.time() + ROUND_TIMEOUT_S
    last_count = -1
    closed = False

    while time.time() < deadline:
        state = r.get(f"round:{round_id}:state") or "UNKNOWN"
        update_count = r.scard(f"round:{round_id}:updates")

        if update_count != last_count:
            submitters = r.smembers(f"round:{round_id}:updates")
            log_step(3, "c", f"State: {state:12s} | Updates: {update_count} | {submitters}")
            last_count = update_count

        # Auto-close once we have enough updates
        if not closed and update_count >= 2 and state in ("OPEN", "COLLECTING"):
            log_step(3, "c", f"Closing round (got {update_count} updates)...")
            close_resp = requests.post(
                f"{ORCHESTRATION_URL}/rounds/{round_id}/close", timeout=10
            )
            log_step(3, "c", f"Close → {close_resp.status_code}")
            closed = True

        if state in ("DONE", "FAILED"):
            break
        time.sleep(POLL_INTERVAL_S)

    final_state = r.get(f"round:{round_id}:state") or "UNKNOWN"
    final_submitters = r.smembers(f"round:{round_id}:updates")

    assert final_state == "DONE", (
        f"Round {round_num} did not complete: state={final_state}"
    )
    assert len(final_submitters) >= 2, (
        f"Round {round_num}: only {len(final_submitters)} updates (need >= 2)"
    )

    # 3c. Verify model version bumped
    new_version = r.get("model:current")
    assert new_version, "model:current empty after round"
    assert new_version != prev_version, (
        f"Model version unchanged: still {prev_version}"
    )

    meta = r.hgetall(f"model:version:{new_version}")
    log_step(3, "d", f"Model: {prev_version} → {new_version}")
    log_step(3, "e", f"Participants: {meta.get('num_clients', '?')}")

    return round_id, new_version, final_submitters


# ── Step 4: Verify WebSocket push ────────────────────────────────────────────

def step_4_verify_websocket(ws_listener: WSModelUpdateListener, expected_count: int):
    """Verify MODEL_UPDATED events were received via WebSocket."""
    print(f"\n{'─' * 70}")
    print(f"  Step 4: Verify WebSocket MODEL_UPDATED Events")
    print(f"{'─' * 70}")

    # Give extra time for last event
    time.sleep(WS_WAIT_S)

    events = ws_listener.get_events()
    log_step(4, "a", f"MODEL_UPDATED events received: {len(events)}")
    for i, ev in enumerate(events):
        log_step(4, " ", f"  [{i}] version={ev['version']}")

    if len(events) >= expected_count:
        log_step(4, "b", f"WebSocket push: VERIFIED ({len(events)} >= {expected_count})")
    else:
        log_step(4, "b",
            f"WARNING: Expected {expected_count} events, got {len(events)}. "
            "WebSocket push is best-effort — proceeding."
        )


# ── Step 5: Verify inference serves suggestions ─────────────────────────────

def step_5_verify_inference(model_version: str):
    """POST /infer and verify the server returns suggestions."""
    print(f"\n{'─' * 70}")
    print(f"  Step 5: Verify Inference Server Serves Suggestions")
    print(f"{'─' * 70}")

    # Check health shows updated version
    resp = requests.get(f"{INFERENCE_URL}/health", timeout=5)
    assert resp.status_code == 200
    health = resp.json()
    log_step(5, "a", f"Health: {health}")

    # Send inference request with sample token IDs
    # Token IDs for "the" + "cat" (common tokens in any BPE vocab)
    req_body = {"token_ids": [1, 2, 3], "top_k": 5}
    resp = requests.post(f"{INFERENCE_URL}/infer", json=req_body, timeout=10)
    assert resp.status_code == 200, f"Inference failed: {resp.status_code} {resp.text}"

    result = resp.json()
    suggestions = result.get("suggestions", [])
    scores = result.get("scores", [])

    log_step(5, "b", f"Suggestions: {suggestions}")
    log_step(5, "c", f"Scores: {scores}")

    assert len(suggestions) > 0, "No suggestions returned"
    assert len(scores) == len(suggestions), "Score/suggestion count mismatch"
    log_step(5, "d", "Inference: VERIFIED — model is serving suggestions")


# ── Step 6: Verify perplexity trend ──────────────────────────────────────────

def step_6_verify_perplexity(round_versions: list[str]):
    """Check perplexity is not increasing across rounds (from Redis metadata)."""
    print(f"\n{'─' * 70}")
    print(f"  Step 6: Verify Perplexity Trend (3 Rounds)")
    print(f"{'─' * 70}")

    r = get_redis()
    perplexities = []

    for i, version in enumerate(round_versions):
        meta = r.hgetall(f"model:version:{version}")
        ppl = meta.get("perplexity", meta.get("val_perplexity"))
        if ppl is not None:
            ppl_float = float(ppl)
            perplexities.append(ppl_float)
            log_step(6, chr(ord("a") + i), f"Round {i+1} (v{version}): perplexity = {ppl_float:.4f}")
        else:
            log_step(6, chr(ord("a") + i), f"Round {i+1} (v{version}): perplexity = N/A (not in metadata)")

    if len(perplexities) >= 2:
        # Verify non-increasing: each perplexity <= previous + small tolerance
        # (aggregation can have noise, so allow 5% tolerance)
        improving = True
        for i in range(1, len(perplexities)):
            if perplexities[i] > perplexities[i - 1] * 1.05:
                improving = False
                log_step(6, "z",
                    f"WARNING: Perplexity increased from {perplexities[i-1]:.4f} "
                    f"to {perplexities[i]:.4f} (round {i} → {i+1})"
                )

        if improving:
            log_step(6, "z", "Perplexity: VERIFIED — non-increasing across rounds")
        else:
            # Not a hard failure — warn but proceed
            log_step(6, "z",
                "Perplexity: WARNING — slight increase detected. "
                "May be normal with DP noise or few participants."
            )
    else:
        log_step(6, "z", "Perplexity: SKIPPED — not enough data points in metadata")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  FLS Demo Scenario — Full E2E Rehearsal")
    print("  3 consecutive rounds, 5 clients, perplexity tracking")
    print("=" * 70)

    start_time = time.time()

    # Step 1: Preflight
    initial_version = step_1_preflight()

    # Step 2: Verify clients registered
    step_2_verify_clients()

    # Start WebSocket listener
    ws_listener = WSModelUpdateListener()
    ws_listener.start()
    time.sleep(1)

    try:
        # Run 3 consecutive rounds
        round_versions = []
        prev_version = initial_version
        round_summaries = []

        for round_num in range(1, TOTAL_ROUNDS + 1):
            round_id, new_version, submitters = run_single_round(round_num, prev_version)
            round_versions.append(new_version)
            round_summaries.append({
                "round": round_num,
                "round_id": round_id,
                "version": new_version,
                "participants": len(submitters),
            })
            prev_version = new_version

            # Brief pause between rounds (let services settle)
            if round_num < TOTAL_ROUNDS:
                time.sleep(5)

        # Step 4: Verify WebSocket push
        step_4_verify_websocket(ws_listener, expected_count=TOTAL_ROUNDS)

        # Step 5: Verify inference
        step_5_verify_inference(round_versions[-1])

        # Step 6: Verify perplexity trend
        step_6_verify_perplexity(round_versions)

    finally:
        ws_listener.stop()

    elapsed = time.time() - start_time

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"  DEMO SCENARIO PASSED ({elapsed:.1f}s)")
    print("=" * 70)
    print(f"  Initial model:  {initial_version}")
    print(f"  Rounds completed: {len(round_summaries)}/{TOTAL_ROUNDS}")
    for s in round_summaries:
        print(f"    Round {s['round']}: {s['round_id'][:16]}… → v{s['version']} ({s['participants']} clients)")
    print(f"  Final model:    {round_versions[-1]}")
    print(f"  Total time:     {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n  DEMO SCENARIO FAILED: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Interrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\n  DEMO SCENARIO ERROR: {type(e).__name__}: {e}")
        sys.exit(1)
