"""
client/fl-client/web_bridge.py

FastAPI endpoint that receives training data from the web keyboard UI.
Runs as a sidecar to the FL client agent, appending keystroke events
to the client's local dataset file.

Endpoints:
    POST /training-buffer — accepts token events from the web keyboard

Usage:
    uvicorn client.fl_client.web_bridge:app --host 0.0.0.0 --port 8090

Environment:
    CLIENT_PROFILE  — client profile name (default: "tech")
    DATA_DIR        — directory where dataset files live (default: "/data")
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("web_bridge")

CLIENT_PROFILE = os.environ.get("CLIENT_PROFILE", os.environ.get("PROFILE", "tech"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

app = FastAPI(title="FL Client Web Bridge", version="0.1.0")


class TrainingEvent(BaseModel):
    token_id: int
    accepted: bool
    timestamp_ms: int


class TrainingBufferRequest(BaseModel):
    events: list[TrainingEvent]


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/training-buffer")
def receive_training_buffer(req: TrainingBufferRequest):
    """Append web keyboard training events to the client dataset."""
    if not req.events:
        raise HTTPException(status_code=400, detail="Empty event list")

    dataset_path = DATA_DIR / f"client-{CLIENT_PROFILE}.json"

    # Load existing dataset
    existing: list[dict] = []
    if dataset_path.exists():
        try:
            with open(dataset_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("Could not read existing dataset, starting fresh")
            existing = []

    # Convert web events to the training format expected by local_trainer.py:
    # { "token_id": int, "context_ids": [int, ...], "timestamp_ms": int }
    # For web-captured events we store a minimal context from sequential tokens.
    context_window: list[int] = []
    new_events: list[dict] = []

    for event in req.events:
        # Build context from the preceding tokens in this buffer
        new_events.append({
            "token_id": event.token_id,
            "context_ids": list(context_window[-10:]),  # last 10 tokens
            "timestamp_ms": event.timestamp_ms,
            "accepted": event.accepted,  # extra field: whether user accepted a suggestion
        })
        context_window.append(event.token_id)

    existing.extend(new_events)

    # Write back
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(dataset_path, "w") as f:
        json.dump(existing, f)

    log.info(
        "Appended %d events to %s (total: %d)",
        len(new_events),
        dataset_path,
        len(existing),
    )

    return {
        "status": "ok",
        "appended": len(new_events),
        "total": len(existing),
    }
