"""
services/websocket-push/tests/test_websocket.py

Integration tests for the WebSocket Push service.

Usage:
    # Start websocket-push on port 8087 first, then:
    python services/websocket-push/tests/test_websocket.py

Prerequisites:
    - websocket-push running on localhost:8087 (or WS_PORT env)
    - Redis accessible on localhost:6379
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import redis
import websockets

PORT = os.environ.get("WS_PORT", "8087")
BASE_WS = f"ws://localhost:{PORT}/ws"
BASE_HTTP = f"http://localhost:{PORT}"


async def test_websocket_push():
    """Test: MODEL_UPDATED event pushed to WebSocket client."""
    r = redis.Redis(decode_responses=True)

    async with websockets.connect(BASE_WS) as ws:
        # Let connection establish
        await asyncio.sleep(0.3)

        # Check connection count
        resp = httpx.get(f"{BASE_HTTP}/connections")
        assert resp.status_code == 200
        count = resp.json()["count"]
        print(f"Active connections: {count}")
        assert count >= 1, f"expected at least 1 connection, got {count}"

        # Publish a MODEL_UPDATED event on Redis
        r.publish("fl:model:updated", json.dumps({
            "event": "MODEL_UPDATED",
            "payload": {
                "version": "v1.0.1",
                "model_url": "http://minio/test",
                "released_at": int(time.time()),
            },
        }))

        # Wait for push message
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            data = json.loads(msg)
            print(f"Received push: {data}")
            assert data["event"] == "MODEL_UPDATED"
            assert data["payload"]["version"] == "v1.0.1"
            print("[PASS] MODEL_UPDATED received")
        except asyncio.TimeoutError:
            assert False, "No push message received within 3 seconds"

    # After close, count should drop
    await asyncio.sleep(0.3)
    resp = httpx.get(f"{BASE_HTTP}/connections")
    count_after = resp.json()["count"]
    print(f"Connections after close: {count_after}")


async def test_round_events():
    """Test: ROUND_OPENED event pushed to WebSocket client."""
    r = redis.Redis(decode_responses=True)

    async with websockets.connect(BASE_WS) as ws:
        await asyncio.sleep(0.2)

        r.publish("fl:round:events", json.dumps({
            "event": "ROUND_OPENED",
            "round_id": "round-test-ws",
        }))

        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            data = json.loads(msg)
            print(f"Received round event: {data}")
            assert data["event"] == "ROUND_OPENED"
            assert data["round_id"] == "round-test-ws"
            print("[PASS] ROUND_OPENED received")
        except asyncio.TimeoutError:
            assert False, "No round event received within 3 seconds"


async def test_healthz():
    """Test: Health check."""
    resp = httpx.get(f"{BASE_HTTP}/healthz")
    assert resp.status_code == 200
    print("[PASS] Healthz OK")


async def main():
    await test_healthz()
    await test_websocket_push()
    await test_round_events()
    print("\nALL WEBSOCKET PUSH TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
