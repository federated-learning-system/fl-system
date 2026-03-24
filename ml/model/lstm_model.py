"""
ml/model/lstm_model.py

Two-layer LSTM for next-word prediction in the FLS federated learning system.

Architecture:
    Embedding(8192, 128, padding_idx=0)
    → LSTM(128, 256, num_layers=2, dropout=0.2, batch_first=True)
    → Linear(256, 8192)

Input:  token_ids [batch, seq_len=10]
Output: logits [batch, vocab_size=8192], hidden (h_n, c_n)

Parameter count: ~4.08M

Usage:
    from ml.model.lstm_model import NextWordLSTM
    model = NextWordLSTM()
    logits, hidden = model(token_ids)
"""

from __future__ import annotations

from typing import Optional, Tuple

import torch
import torch.nn as nn

from ml.model.model_config import ModelConfig


class NextWordLSTM(nn.Module):
    """
    Input:  token_ids [batch, seq_len=10]
    Output: logits [batch, vocab_size=8192]
    """

    def __init__(
        self,
        vocab_size: int = 8192,
        embed_dim: int = 128,
        hidden_size: int = 256,
        num_layers: int = 2,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.embed_dim = embed_dim
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm = nn.LSTM(
            embed_dim,
            hidden_size,
            num_layers,
            dropout=dropout,
            batch_first=True,
        )
        self.output = nn.Linear(hidden_size, vocab_size)

    def forward(
        self,
        token_ids: torch.Tensor,
        hidden: Optional[Tuple[torch.Tensor, torch.Tensor]] = None,
    ) -> Tuple[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
        # token_ids: [B, S]
        emb = self.embedding(token_ids)       # [B, S, E]
        out, hidden = self.lstm(emb, hidden)  # [B, S, H]
        logits = self.output(out[:, -1, :])   # [B, V] — last timestep
        return logits, hidden

    @classmethod
    def from_config(cls, config: ModelConfig) -> NextWordLSTM:
        """Construct a model from a ModelConfig dataclass."""
        return cls(
            vocab_size=config.vocab_size,
            embed_dim=config.embed_dim,
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            dropout=config.dropout,
        )
