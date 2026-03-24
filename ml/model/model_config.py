"""
ml/model/model_config.py

Dataclass holding all LSTM hyperparameters for the FLS next-word prediction model.
Serializable to/from JSON for storage alongside model checkpoints.

Usage:
    from ml.model.model_config import ModelConfig

    cfg = ModelConfig()
    cfg.to_json("config.json")
    cfg2 = ModelConfig.from_json("config.json")
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ModelConfig:
    """Hyperparameters for NextWordLSTM."""

    vocab_size: int = 8192
    embed_dim: int = 128
    hidden_size: int = 256
    num_layers: int = 2
    dropout: float = 0.2
    seq_len: int = 10
    padding_idx: int = 0  # [PAD] token

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: str | Path) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> ModelConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, path: str | Path) -> ModelConfig:
        with open(path) as f:
            return cls.from_dict(json.load(f))
