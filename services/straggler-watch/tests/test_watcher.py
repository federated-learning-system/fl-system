"""
services/straggler-watch/tests/test_watcher.py

Integration tests for the Straggler Watch service.

Usage:
    # Start the straggler-watch service first, then:
    python services/straggler-watch/tests/test_watcher.py

Prerequisites:
    - straggler-watch running and subscribed to Redis
    - Redis accessible on localhost:6379
"""

from __future__ import annotations

import json
import time

import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


def test_straggler_detection():
    """Test: Stragglers are detected after deadline expires."""
    round_id = "round-straggler-test"

    # Clean up any previous test data
    for key in [
        f"round:{round_id}:state",
        f"round:{round_id}:config",
        f"round:{round_id}:updates",
        f"round:{round_id}:stragglers",
    ]:
        r.delete(key)

    # Simulate a round with 3s deadline
    deadline_unix = int(time.time()) + 3
    r.set(f"round:{round_id}:state", "OPEN")
    r.hset(f"round:{round_id}:config", mapping={
        "expected_clients": json.dumps(["client-a", "client-b", "client-c"]),
        "deadline_unix": str(deadline_unix),
    })

    # Only client-a submits
    r.sadd(f"round:{round_id}:updates", "client-a")

    # Publish ROUND_OPEN event
    r.publish("fl:round:events", json.dumps({
        "event": "ROUND_OPEN",
        "round_id": round_id,
        "deadline_unix": deadline_unix,
    }))

    print(f"Published ROUND_OPEN with deadline in 3s (unix={deadline_unix})")

    # Wait for straggler watch to fire (3s deadline + 2s buffer)
    time.sleep(5)

    # Check stragglers were marked
    stragglers = r.smembers(f"round:{round_id}:stragglers")
    print(f"Stragglers detected: {stragglers}")
    assert "client-b" in stragglers, "client-b should be straggler"
    assert "client-c" in stragglers, "client-c should be straggler"
    assert "client-a" not in stragglers, "client-a should not be straggler (submitted)"

    # Check ROUND_CLOSE was published (round state updated)
    round_state = r.get(f"round:{round_id}:state")
    print(f"Round state after deadline: {round_state}")
    assert round_state in ["CLOSED", "AGGREGATING"], \
        f"round should be closed after deadline, got: {round_state}"

    # Check straggler stream entry
    entries = r.xrange(f"fl:straggler:stream", "-", "+", count=10)
    found = False
    for entry_id, fields in entries:
        if fields.get("round_id") == round_id:
            found = True
            print(f"Stream entry: {fields}")
            break
    assert found, "straggler stream entry not found"


def test_early_close_cancels_watcher():
    """Test: Closing a round early cancels the straggler watcher."""
    round_id = "round-early-close-test"

    # Clean up
    for key in [
        f"round:{round_id}:state",
        f"round:{round_id}:config",
        f"round:{round_id}:updates",
        f"round:{round_id}:stragglers",
    ]:
        r.delete(key)

    # Set up round with 10s deadline
    deadline_unix = int(time.time()) + 10
    r.set(f"round:{round_id}:state", "OPEN")
    r.hset(f"round:{round_id}:config", mapping={
        "expected_clients": json.dumps(["client-x", "client-y"]),
        "deadline_unix": str(deadline_unix),
    })

    # Publish ROUND_OPEN
    r.publish("fl:round:events", json.dumps({
        "event": "ROUND_OPEN",
        "round_id": round_id,
        "deadline_unix": deadline_unix,
    }))

    time.sleep(1)

    # Close the round early
    r.set(f"round:{round_id}:state", "CLOSED")
    r.publish("fl:round:events", json.dumps({
        "event": "ROUND_CLOSED",
        "round_id": round_id,
    }))

    print("Published early ROUND_CLOSED")

    # Wait a bit — should NOT create stragglers since we closed early
    time.sleep(2)

    stragglers = r.smembers(f"round:{round_id}:stragglers")
    print(f"Stragglers after early close: {stragglers}")
    assert len(stragglers) == 0, \
        f"early-closed round should have no stragglers, got: {stragglers}"


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_straggler_detection()
    print("[PASS] Straggler detection")

    test_early_close_cancels_watcher()
    print("[PASS] Early close cancels watcher")

    print("\nALL STRAGGLER WATCH TESTS PASSED")
