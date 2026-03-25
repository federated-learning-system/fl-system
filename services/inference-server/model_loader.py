"""
services/inference-server/model_loader.py

Downloads ONNX model + tokenizer from MinIO and manages an ONNX Runtime
inference session with atomic hot-swap on model updates.

Usage:
    from services.inference_server.model_loader import ModelManager

    mgr = ModelManager()
    mgr.load_initial()           # blocking — loads current model version
    mgr.reload()                 # hot-swap to latest version
    logits = mgr.infer(token_ids)  # numpy array [1, vocab_size]
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import onnxruntime as ort

log = logging.getLogger("inference-server.model_loader")

# ── Path setup ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(_REPO_ROOT))

from services.shared.redis_client import get_client as get_redis
from services.shared.minio_client import (
    get_client as get_minio,
    BUCKET_MODELS,
    download_blob,
    object_exists,
)
from ml.tokenizer.tokenizer import FLTokenizer
from ml.model.model_config import ModelConfig


class ModelManager:
    """
    Thread-safe ONNX model manager with atomic hot-swap.

    Holds the current ONNX Runtime session, tokenizer, and model version.
    Reload is atomic: a new session is created, then swapped in under a lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: Optional[ort.InferenceSession] = None
        self._tokenizer: Optional[FLTokenizer] = None
        self._model_version: str = "unknown"
        self._config = ModelConfig()
        self._redis = get_redis()

        # Local cache directory for downloaded models
        self._cache_dir = Path(tempfile.mkdtemp(prefix="fl-inference-"))
        log.info("Model cache dir: %s", self._cache_dir)

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def tokenizer(self) -> FLTokenizer:
        if self._tokenizer is None:
            raise RuntimeError("Tokenizer not loaded")
        return self._tokenizer

    @property
    def is_ready(self) -> bool:
        return self._session is not None and self._tokenizer is not None

    def load_initial(self) -> None:
        """Load the current model version from MinIO. Blocks until ready."""
        # Load tokenizer first (only once — vocab doesn't change)
        self._load_tokenizer()

        # Get current model version from Redis
        version = self._redis.get("model:current")
        if version is None:
            version = "v1.0.0"
            log.warning("No model:current in Redis, defaulting to %s", version)

        self._load_model(version)

    def reload(self) -> str:
        """
        Hot-swap to the latest model version.
        Returns the new version string.
        """
        version = self._redis.get("model:current")
        if version is None:
            log.warning("No model:current in Redis")
            return self._model_version

        if version == self._model_version:
            log.info("Already serving %s, skip reload", version)
            return version

        log.info("Reloading model: %s → %s", self._model_version, version)
        self._load_model(version)
        return version

    def infer(self, token_ids: list[int], top_k: int = 3) -> tuple[list[int], np.ndarray]:
        """
        Run inference on a sequence of token IDs.

        Parameters
        ----------
        token_ids : list[int]
            Input token IDs (will be padded/truncated to seq_len=10).
        top_k : int
            Number of top predictions to return.

        Returns
        -------
        (top_k_ids, top_k_scores) : (list[int], ndarray of shape [top_k])
        """
        with self._lock:
            if self._session is None:
                raise RuntimeError("Model not loaded")
            session = self._session

        # Pad or truncate to seq_len
        seq_len = self._config.seq_len
        if len(token_ids) < seq_len:
            # Left-pad with PAD_ID
            padded = [self._config.padding_idx] * (seq_len - len(token_ids)) + token_ids
        else:
            padded = token_ids[-seq_len:]

        # Prepare inputs
        input_ids = np.array([padded], dtype=np.int64)
        hidden_h = np.zeros((self._config.num_layers, 1, self._config.hidden_size), dtype=np.float32)
        hidden_c = np.zeros((self._config.num_layers, 1, self._config.hidden_size), dtype=np.float32)

        # Run ONNX session
        outputs = session.run(
            None,
            {
                "token_ids": input_ids,
                "hidden_h": hidden_h,
                "hidden_c": hidden_c,
            },
        )

        logits = outputs[0][0]  # shape: [vocab_size]

        # Softmax for scores
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        # Top-k
        top_k_indices = np.argsort(probs)[-top_k:][::-1]
        top_k_scores = probs[top_k_indices]

        return top_k_indices.tolist(), top_k_scores

    def decode_tokens(self, token_ids: list[int]) -> list[str]:
        """Decode a list of token IDs to their string pieces."""
        return [self.tokenizer.decode_single(tid) for tid in token_ids]

    # ── Internal ─────────────────────────────────────────────────────

    def _load_tokenizer(self) -> None:
        """Download and load the SentencePiece tokenizer from MinIO."""
        vocab_key = "vocab/vocab_8192.model"
        local_path = self._cache_dir / "vocab_8192.model"

        if not local_path.exists():
            log.info("Downloading tokenizer from MinIO: %s", vocab_key)
            download_blob(BUCKET_MODELS, vocab_key, str(local_path))

        self._tokenizer = FLTokenizer(str(local_path))
        log.info("Tokenizer loaded: vocab_size=%d", self._tokenizer.vocab_size())

    def _load_model(self, version: str) -> None:
        """Download ONNX model from MinIO and create a new session."""
        # Try quantized model first (smaller, faster)
        quant_key = f"models/{version}/model_quant.onnx"
        full_key = f"models/{version}/model.onnx"

        local_path = self._cache_dir / f"model_{version}.onnx"

        if object_exists(BUCKET_MODELS, quant_key):
            log.info("Downloading quantized model: %s", quant_key)
            download_blob(BUCKET_MODELS, quant_key, str(local_path))
        elif object_exists(BUCKET_MODELS, full_key):
            log.info("Downloading full model: %s", full_key)
            download_blob(BUCKET_MODELS, full_key, str(local_path))
        else:
            log.error("No ONNX model found for version %s", version)
            return

        # Create new ONNX session
        sess_options = ort.SessionOptions()
        sess_options.inter_op_num_threads = 2
        sess_options.intra_op_num_threads = 2
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        new_session = ort.InferenceSession(
            str(local_path),
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )

        # Atomic swap under lock
        with self._lock:
            old_session = self._session
            self._session = new_session
            self._model_version = version

        log.info("Model loaded: version=%s, path=%s", version, local_path)

        # Clean up old model file (keep current)
        for f in self._cache_dir.glob("model_*.onnx"):
            if f != local_path:
                try:
                    f.unlink()
                except OSError:
                    pass
