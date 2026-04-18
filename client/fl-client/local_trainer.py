"""
client/fl-client/local_trainer.py

Local on-device trainer for simulated FL clients.

Loads the global model checkpoint (.pt), trains for N local epochs on the
client's synthetic keystroke data using FedProx regularisation, then computes
the model delta (w_local - w_global).

The delta is passed to DPEngine for clipping + noise before submission.

Usage:
    from local_trainer import LocalTrainer

    trainer = LocalTrainer(model_path="ml/training/warmstart_final.pt")
    delta = trainer.train(dataset, local_epochs=1, batch_size=32,
                          global_model_path="ml/training/warmstart_final.pt",
                          fedprox_mu=0.01)
"""

from __future__ import annotations

import copy
import logging
from typing import Dict, List

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

log = logging.getLogger(__name__)


class LocalTrainer:
    """Trains a NextWordLSTM on local data and returns the weight delta."""

    # Default model architecture — matches the seeded LSTM in ml/model/
    _DEFAULT_MODEL_CONFIG = {
        "vocab_size": 8192, "embed_dim": 128, "hidden_size": 256,
        "num_layers": 2, "dropout": 0.2, "seq_len": 10, "padding_idx": 0,
    }

    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
        # Support both full checkpoint format and raw state_dict (FedAvg output)
        if isinstance(ckpt, dict) and "model_state_dict" in ckpt:
            self._checkpoint = ckpt
            self._model_config = ckpt.get("model_config", self._DEFAULT_MODEL_CONFIG)
            self._state_dict = ckpt["model_state_dict"]
        else:
            self._checkpoint = ckpt
            self._model_config = self._DEFAULT_MODEL_CONFIG
            self._state_dict = ckpt

    def _build_model(self) -> nn.Module:
        """Reconstruct the LSTM model from checkpoint config."""
        from ml.model.lstm_model import NextWordLSTM
        from ml.model.model_config import ModelConfig

        config = ModelConfig.from_dict(self._model_config)
        model = NextWordLSTM.from_config(config)
        model.load_state_dict(self._state_dict)
        return model

    def _prepare_data(
        self, dataset: List[dict], batch_size: int
    ) -> DataLoader:
        """
        Convert raw keystroke events to a DataLoader.

        Each event has:
            {"token_id": int, "context_ids": [int, ...], "timestamp_ms": int}

        We build:
            X = context_ids  [N, seq_len=10]
            Y = token_id     [N]
        """
        contexts = []
        targets = []
        for event in dataset:
            contexts.append(event["context_ids"])
            targets.append(event["token_id"])

        X = torch.tensor(contexts, dtype=torch.long)
        Y = torch.tensor(targets, dtype=torch.long)

        ds = TensorDataset(X, Y)
        return DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=False)

    def train(
        self,
        dataset: List[dict],
        local_epochs: int = 1,
        batch_size: int = 32,
        global_model_path: str | None = None,
        fedprox_mu: float = 0.01,
        learning_rate: float = 1e-3,
    ) -> Dict[str, torch.Tensor]:
        """
        Train locally and return the weight delta.

        Args:
            dataset: List of keystroke events (token_id, context_ids, timestamp_ms).
            local_epochs: Number of local training epochs.
            batch_size: Mini-batch size.
            global_model_path: Path to the global model (for FedProx term).
                               If None, uses self._model_path.
            fedprox_mu: FedProx regularisation strength.
            learning_rate: Adam learning rate.

        Returns:
            delta: dict of {param_name: (w_local - w_global)} tensors.
        """
        if not dataset:
            raise ValueError("Dataset is empty — cannot train")

        # Build local model (starts from global weights)
        model = self._build_model()
        model.train()

        # Snapshot the global weights for FedProx term and delta computation
        global_state = copy.deepcopy(model.state_dict())

        # Prepare data
        loader = self._prepare_data(dataset, batch_size)

        # Optimizer
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        loss_fn = nn.CrossEntropyLoss(ignore_index=0)

        # Training loop
        total_loss = 0.0
        total_samples = 0

        for epoch in range(local_epochs):
            epoch_loss = 0.0
            for X_batch, Y_batch in loader:
                optimizer.zero_grad()

                logits, _ = model(X_batch)
                ce_loss = loss_fn(logits, Y_batch)

                # FedProx regularisation: (mu/2) * ||w_local - w_global||^2
                prox_term = 0.0
                if fedprox_mu > 0:
                    for name, param in model.named_parameters():
                        if name in global_state:
                            prox_term += torch.sum(
                                (param - global_state[name].detach()) ** 2
                            )
                    prox_term = (fedprox_mu / 2.0) * prox_term

                loss = ce_loss + prox_term
                loss.backward()

                # Gradient clipping for training stability
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)

                optimizer.step()

                epoch_loss += ce_loss.item() * X_batch.size(0)
                total_samples += X_batch.size(0)

            total_loss += epoch_loss
            avg_loss = epoch_loss / max(len(loader.dataset), 1)
            log.info("Epoch %d/%d — loss: %.4f", epoch + 1, local_epochs, avg_loss)

        # Compute delta = w_local - w_global
        local_state = model.state_dict()
        delta: Dict[str, torch.Tensor] = {}
        for name in global_state:
            delta[name] = local_state[name] - global_state[name]

        avg_total = total_loss / max(total_samples, 1)
        log.info(
            "Local training complete: %d epochs, %d samples, avg_loss=%.4f",
            local_epochs,
            len(dataset),
            avg_total,
        )

        return delta

    @property
    def num_params(self) -> int:
        """Return total number of trainable parameters."""
        model = self._build_model()
        return sum(p.numel() for p in model.parameters())
