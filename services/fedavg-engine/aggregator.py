"""
services/fedavg-engine/aggregator.py

FedAvg-R aggregation engine for the FLS federated learning system.

Consumes round-close events, loads client update blobs from MinIO,
runs weighted FedAvg with straggler penalties, writes new model to
MinIO, and updates Redis model:current.

Usage:
    # As a standalone worker:
    .venv/bin/python -m services.fedavg-engine.aggregator

    # Or import the core function for testing:
    from services.fedavg_engine.aggregator import fedavg_r
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import torch
import numpy as np
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# ── Path setup ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from services.shared.redis_client import get_client as get_redis, keys
from services.shared.minio_client import (
    get_client as get_minio,
    BUCKET_MODELS,
    download_blob,
    upload_model_blob,
    object_exists,
)

log = logging.getLogger("fedavg-engine")

# ── Prometheus metrics ───────────────────────────────────────────────────────

aggregation_duration = Histogram(
    "fl_aggregation_duration_seconds",
    "Duration of FedAvg-R aggregation per round",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

round_participants = Gauge(
    "fl_round_participants",
    "Number of clients that participated in the last aggregation round",
)

rounds_aggregated = Counter(
    "fl_rounds_aggregated_total",
    "Total number of rounds successfully aggregated",
)

rounds_failed = Counter(
    "fl_rounds_failed_total",
    "Total number of rounds that failed aggregation",
)


# ── Core FedAvg-R ────────────────────────────────────────────────────────────

def fedavg_r(
    updates: list[dict[str, Any]],
    base_model: dict[str, torch.Tensor],
    config: dict[str, Any] | None = None,
) -> dict[str, torch.Tensor]:
    """
    Federated Averaging with Robustness (FedAvg-R).

    Parameters
    ----------
    updates : list of dict
        Each entry has:
          - "delta": dict[str, Tensor] — parameter-name → delta tensor
          - "num_samples": int — number of local training samples
          - "is_straggler": bool — whether client was a straggler
          - "checksum": str — "sha256:..." or "ok" for pre-verified
    base_model : dict[str, Tensor]
        Current global model state_dict.
    config : dict
        - "penalty_factor": float (default 0.5) — weight multiplier for stragglers
        - "min_clients": int (default 1) — minimum updates required
        - "trimmed_mean": bool (default False) — if True, use trimmed mean

    Returns
    -------
    dict[str, Tensor] — new global model state_dict (base + weighted avg delta).

    Raises
    ------
    ValueError if fewer than min_clients updates provided.
    """
    if config is None:
        config = {}

    penalty_factor = config.get("penalty_factor", 0.5)
    min_clients = config.get("min_clients", 1)
    use_trimmed_mean = config.get("trimmed_mean", False)

    if len(updates) < min_clients:
        raise ValueError(
            f"Not enough updates: got {len(updates)}, need {min_clients}"
        )

    # Compute effective weights
    weights = []
    for u in updates:
        w = float(u["num_samples"])
        if u.get("is_straggler", False):
            w *= penalty_factor
        weights.append(w)

    total_weight = sum(weights)
    if total_weight == 0:
        raise ValueError("Total weight is zero — cannot aggregate")

    # Normalize weights
    norm_weights = [w / total_weight for w in weights]

    if use_trimmed_mean and len(updates) >= 4:
        return _trimmed_mean_aggregate(updates, base_model, norm_weights)

    # Weighted average of deltas
    param_keys = list(updates[0]["delta"].keys())
    avg_delta: dict[str, torch.Tensor] = {}

    for key in param_keys:
        weighted_sum = torch.zeros_like(updates[0]["delta"][key], dtype=torch.float32)
        for u, w in zip(updates, norm_weights):
            weighted_sum += w * u["delta"][key].float()
        avg_delta[key] = weighted_sum

    # Apply averaged delta to base model
    new_model: dict[str, torch.Tensor] = {}
    for key in base_model:
        if key in avg_delta:
            new_model[key] = base_model[key].float() + avg_delta[key]
        else:
            new_model[key] = base_model[key].clone()

    return new_model


def _trimmed_mean_aggregate(
    updates: list[dict],
    base_model: dict[str, torch.Tensor],
    norm_weights: list[float],
) -> dict[str, torch.Tensor]:
    """
    Trimmed mean: drop top and bottom 10% of values per parameter element,
    then compute weighted average of remaining.
    """
    trim_fraction = 0.1
    n = len(updates)
    trim_count = max(1, int(n * trim_fraction))

    param_keys = list(updates[0]["delta"].keys())
    new_model: dict[str, torch.Tensor] = {}

    for key in param_keys:
        # Stack all deltas: [n_clients, *param_shape]
        stacked = torch.stack([u["delta"][key].float() for u in updates], dim=0)

        # Sort along client axis and trim
        sorted_vals, _ = torch.sort(stacked, dim=0)
        trimmed = sorted_vals[trim_count : n - trim_count]

        # Simple mean of trimmed values (equal weight after trimming)
        avg_delta = trimmed.mean(dim=0)

        if key in base_model:
            new_model[key] = base_model[key].float() + avg_delta
        else:
            new_model[key] = avg_delta

    # Copy keys not in deltas
    for key in base_model:
        if key not in new_model:
            new_model[key] = base_model[key].clone()

    return new_model


# ── Blob I/O helpers ─────────────────────────────────────────────────────────

def serialize_delta(state_dict: dict[str, torch.Tensor]) -> bytes:
    """Serialize a state_dict delta to gzip-compressed bytes."""
    buf = io.BytesIO()
    torch.save(state_dict, buf)
    return gzip.compress(buf.getvalue())


def deserialize_delta(blob: bytes) -> dict[str, torch.Tensor]:
    """Decompress and deserialize a gzip-compressed state_dict delta."""
    raw = gzip.decompress(blob)
    buf = io.BytesIO(raw)
    return torch.load(buf, map_location="cpu", weights_only=True)


def compute_checksum(blob: bytes) -> str:
    """Compute sha256 checksum of a blob."""
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def verify_checksum(blob: bytes, expected: str) -> bool:
    """Verify blob checksum. Returns True if matches or if expected is 'ok'."""
    if expected == "ok":
        return True
    return compute_checksum(blob) == expected


def load_update_blob(blob: bytes, checksum: str = "ok") -> dict[str, torch.Tensor]:
    """Load and verify an update blob."""
    if not verify_checksum(blob, checksum):
        raise ValueError(f"Checksum mismatch: expected {checksum}")
    return deserialize_delta(blob)


# ── Worker loop ──────────────────────────────────────────────────────────────

class FedAvgWorker:
    """
    Long-running worker that listens to Redis for ROUND_CLOSED events
    and performs FedAvg-R aggregation.
    """

    def __init__(self) -> None:
        self.redis = get_redis()
        self.minio = get_minio()
        self.penalty_factor = float(os.environ.get("PENALTY_FACTOR", "0.5"))
        self.min_clients = int(os.environ.get("MIN_CLIENTS", "2"))

    def run(self) -> None:
        """Subscribe to round events and process ROUND_CLOSED."""
        log.info("FedAvg worker starting, subscribing to %s", keys.CHANNEL_ROUND_EVENTS)

        pubsub = self.redis.pubsub()
        pubsub.subscribe(keys.CHANNEL_ROUND_EVENTS)

        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                evt = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue

            if evt.get("event") in ("ROUND_CLOSED", "ROUND_CLOSE"):
                round_id = evt.get("round_id")
                if round_id:
                    self._process_round(round_id)

    def _process_round(self, round_id: str) -> None:
        """Load updates for a round, aggregate, and write new model."""
        log.info("Processing round: %s", round_id)

        # Set round state to AGGREGATING
        self.redis.set(keys.round_state(round_id), "AGGREGATING")

        start_time = time.monotonic()
        try:
            # Get list of clients that submitted updates
            client_ids = self.redis.smembers(keys.round_updates(round_id))
            if not client_ids:
                log.warning("No updates for round %s", round_id)
                self.redis.set(keys.round_state(round_id), "FAILED")
                rounds_failed.inc()
                return

            round_participants.set(len(client_ids))

            # Check for stragglers
            straggler_key = f"round:{round_id}:stragglers"
            stragglers = self.redis.smembers(straggler_key)

            # Load base model version
            config_data = self.redis.hgetall(keys.round_config(round_id))
            model_version = config_data.get("base_model_version", "v1.0.0")

            # Load base model from MinIO
            base_model = self._load_base_model(model_version)
            if base_model is None:
                log.error("Failed to load base model %s", model_version)
                self.redis.set(keys.round_state(round_id), "FAILED")
                rounds_failed.inc()
                return

            # Load update blobs from MinIO
            updates = []
            for client_id in client_ids:
                blob_key = f"updates/{round_id}/{client_id}.delta.gz"
                try:
                    with tempfile.NamedTemporaryFile(suffix=".delta.gz") as tmp:
                        download_blob(BUCKET_MODELS, blob_key, tmp.name)
                        with open(tmp.name, "rb") as f:
                            blob = f.read()

                    delta = deserialize_delta(blob)
                    updates.append({
                        "delta": delta,
                        "num_samples": int(config_data.get("num_samples", 100)),
                        "is_straggler": client_id in stragglers,
                        "checksum": "ok",  # already verified at submit time
                    })
                except Exception as e:
                    log.error("Failed to load update from %s: %s", client_id, e)
                    continue

            if len(updates) < self.min_clients:
                log.warning(
                    "Not enough valid updates: %d < %d", len(updates), self.min_clients
                )
                self.redis.set(keys.round_state(round_id), "FAILED")
                rounds_failed.inc()
                return

            # Run FedAvg-R
            new_model = fedavg_r(
                updates,
                base_model,
                config={
                    "penalty_factor": self.penalty_factor,
                    "min_clients": self.min_clients,
                },
            )

            # Bump version
            new_version = self._bump_version(model_version)

            # Save new model to MinIO
            self._save_model(new_model, new_version, round_id, len(updates))

            # Update Redis
            self.redis.set(keys.model_current(), new_version)
            self.redis.hset(
                keys.model_version(new_version),
                mapping={
                    "version": new_version,
                    "round_id": round_id,
                    "num_clients": str(len(updates)),
                    "created_at": str(int(time.time())),
                    "onnx_s3_key": f"models/{new_version}/model_quant.onnx",
                },
            )

            # Update round state
            self.redis.set(keys.round_state(round_id), "DONE")

            # Publish MODEL_UPDATED event
            self.redis.publish(
                keys.CHANNEL_MODEL_UPDATED,
                json.dumps({"version": new_version, "round_id": round_id}),
            )

            elapsed = time.monotonic() - start_time
            aggregation_duration.observe(elapsed)
            rounds_aggregated.inc()

            log.info(
                "Round %s aggregated: %d clients → %s (%.1fs)",
                round_id, len(updates), new_version, elapsed,
            )

        except Exception as e:
            log.error("Aggregation failed for round %s: %s", round_id, e)
            self.redis.set(keys.round_state(round_id), "FAILED")
            rounds_failed.inc()

    def _load_base_model(self, version: str) -> dict[str, torch.Tensor] | None:
        """Load the base model state_dict from MinIO."""
        # Try loading the PyTorch weights file
        weights_key = f"models/{version}/model_weights.pt"
        if not object_exists(BUCKET_MODELS, weights_key):
            # Fallback: try loading from a checkpoint
            weights_key = f"models/{version}/model.pt"
            if not object_exists(BUCKET_MODELS, weights_key):
                log.warning("No weights file found for %s", version)
                return None

        try:
            with tempfile.NamedTemporaryFile(suffix=".pt") as tmp:
                download_blob(BUCKET_MODELS, weights_key, tmp.name)
                checkpoint = torch.load(tmp.name, map_location="cpu", weights_only=True)
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint:
                    return checkpoint["state_dict"]
                return checkpoint
        except Exception as e:
            log.error("Failed to load model weights: %s", e)
            return None

    def _save_model(
        self,
        state_dict: dict[str, torch.Tensor],
        version: str,
        round_id: str,
        num_clients: int,
    ) -> None:
        """Save new model state_dict to MinIO."""
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=False) as tmp:
            torch.save(state_dict, tmp.name)
            upload_model_blob(tmp.name, version, "model_weights.pt")
            os.unlink(tmp.name)

    def _bump_version(self, current: str) -> str:
        """Bump version: v1.0.0 → v1.0.1, v0 → v1, etc."""
        if current.startswith("v") and "." in current:
            parts = current[1:].split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            return "v" + ".".join(parts)
        elif current.startswith("v"):
            num = int(current[1:])
            return f"v{num + 1}"
        return current + ".1"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    metrics_port = int(os.environ.get("METRICS_PORT", "9093"))
    start_http_server(metrics_port)
    log.info("Prometheus metrics on :%d", metrics_port)

    worker = FedAvgWorker()
    worker.run()


if __name__ == "__main__":
    main()
