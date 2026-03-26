"""
services/inference-server/main.py

FastAPI inference server for the FLS federated learning system.
Serves next-word predictions from an ONNX Runtime session loaded from MinIO.

Endpoints:
    POST /infer   — {token_ids: [int], top_k: int} → {suggestions: [str], scores: [float]}
    GET  /health  — {status: "ok", model_version: str}
    POST /reload  — hot-swap to latest model version

Usage:
    MINIO_ENDPOINT=http://localhost:29000 \
    .venv/bin/python -m uvicorn services.inference-server.main:app --host 0.0.0.0 --port 8000

    # Or directly:
    .venv/bin/python -m services.inference-server.main
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

# ── Path setup ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_SERVICE_DIR))

from model_loader import ModelManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("inference-server")

# ── Prometheus metrics ───────────────────────────────────────────────────────

inference_latency = Histogram(
    "fl_inference_latency_ms",
    "Inference latency in milliseconds",
    buckets=[5, 10, 20, 50, 100, 200, 500, 1000],
)

# ── Pydantic models ──────────────────────────────────────────────────────────

class InferRequest(BaseModel):
    token_ids: list[int]
    top_k: int = Field(default=3, ge=1, le=20)

class InferResponse(BaseModel):
    suggestions: list[str]
    scores: list[float]

class HealthResponse(BaseModel):
    status: str
    model_version: str

class ReloadResponse(BaseModel):
    status: str
    model_version: str

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="FLS Inference Server", version="1.0.0")

# Module-level model manager — loaded on startup
_mgr: Optional[ModelManager] = None


@app.on_event("startup")
async def startup():
    global _mgr
    _mgr = ModelManager()
    _mgr.load_initial()
    log.info("Inference server ready: model=%s", _mgr.model_version)


@app.post("/infer", response_model=InferResponse)
async def infer(req: InferRequest):
    if _mgr is None or not _mgr.is_ready:
        raise HTTPException(status_code=503, detail="Model not loaded")

    if not req.token_ids:
        raise HTTPException(status_code=400, detail="token_ids must not be empty")

    t0 = time.perf_counter()

    top_k_ids, top_k_scores = _mgr.infer(req.token_ids, top_k=req.top_k)
    suggestions = _mgr.decode_tokens(top_k_ids)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    inference_latency.observe(elapsed_ms)

    return InferResponse(
        suggestions=suggestions,
        scores=[float(s) for s in top_k_scores],
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    if _mgr is None or not _mgr.is_ready:
        raise HTTPException(status_code=503, detail="Model not loaded")

    return HealthResponse(
        status="ok",
        model_version=_mgr.model_version,
    )


@app.post("/reload", response_model=ReloadResponse)
async def reload():
    if _mgr is None:
        raise HTTPException(status_code=503, detail="Server not initialized")

    new_version = _mgr.reload()
    return ReloadResponse(
        status="ok",
        model_version=new_version,
    )


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── Standalone runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
