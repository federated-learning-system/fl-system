"""
ml/dp_engine/dp_engine.py

Client-side Differential Privacy engine for the FLS federated learning system.

Applies per-layer L2 gradient clipping + calibrated Gaussian noise, and tracks
the cumulative privacy budget via Opacus RDP accountant.

Default parameters (from system design Section 14):
    clip_norm=1.0, noise_multiplier=1.1, epsilon=1.0, delta=1e-5

Usage:
    from ml.dp_engine.dp_engine import DPEngine

    dp = DPEngine(clip_norm=1.0, noise_multiplier=1.1,
                  target_epsilon=1.0, target_delta=1e-5)
    noised_delta = dp.clip_and_noise(model_delta, num_samples=500)
    eps = dp.compute_epsilon(num_samples=500, num_steps=1)
"""

from __future__ import annotations

import copy
import logging
from typing import Dict

import torch
from opacus.accountants import RDPAccountant

log = logging.getLogger(__name__)


class DPEngine:
    """Client-side DP: per-layer L2 clipping + Gaussian noise + RDP accounting."""

    def __init__(
        self,
        clip_norm: float = 1.0,
        noise_multiplier: float = 1.1,
        target_epsilon: float = 1.0,
        target_delta: float = 1e-5,
    ) -> None:
        self.clip_norm = clip_norm
        self.noise_multiplier = noise_multiplier
        self.target_epsilon = target_epsilon
        self.target_delta = target_delta

        # RDP accountant tracks cumulative privacy spend
        self._accountant = RDPAccountant()
        self._steps_taken = 0

    # ── Core DP operations ──────────────────────────────────────────────────

    def clip_and_noise(
        self,
        model_delta: Dict[str, torch.Tensor],
        num_samples: int,
    ) -> Dict[str, torch.Tensor]:
        """
        Apply DP to a model delta (param_name → tensor).

        1. Clip each layer's L2 norm to clip_norm.
        2. Add Gaussian noise: N(0, (noise_multiplier * clip_norm)^2 / num_samples^2).
        3. Record the step in the RDP accountant.

        Returns a new dict with the DP-protected delta.
        """
        result: Dict[str, torch.Tensor] = {}
        noise_std = self.noise_multiplier * self.clip_norm / num_samples

        for name, tensor in model_delta.items():
            # Per-layer L2 clipping
            clipped = self._clip_tensor(tensor, self.clip_norm)
            # Gaussian noise
            noise = torch.normal(mean=0.0, std=noise_std, size=clipped.shape)
            result[name] = clipped + noise

        # Record step in accountant
        sample_rate = 1.0 / num_samples  # treat as single-sample subsampling
        self._accountant.step(
            noise_multiplier=self.noise_multiplier,
            sample_rate=sample_rate,
        )
        self._steps_taken += 1

        return result

    def _clip_tensor(self, tensor: torch.Tensor, max_norm: float) -> torch.Tensor:
        """Clip tensor L2 norm to max_norm."""
        norm = torch.norm(tensor, p=2)
        if norm > max_norm:
            return tensor * (max_norm / norm)
        return tensor.clone()

    # ── Privacy accounting ──────────────────────────────────────────────────

    def compute_epsilon(self, num_samples: int, num_steps: int) -> float:
        """
        Compute the epsilon that *would be* spent for the given parameters,
        using a fresh RDP accountant (does not mutate internal state).
        """
        tmp = RDPAccountant()
        sample_rate = 1.0 / num_samples
        for _ in range(num_steps):
            tmp.step(
                noise_multiplier=self.noise_multiplier,
                sample_rate=sample_rate,
            )
        return tmp.get_epsilon(delta=self.target_delta)

    def epsilon_spent(self) -> float:
        """Return cumulative epsilon spent so far."""
        if self._steps_taken == 0:
            return 0.0
        return self._accountant.get_epsilon(delta=self.target_delta)

    def budget_remaining(self) -> float:
        """Return remaining epsilon budget."""
        return max(0.0, self.target_epsilon - self.epsilon_spent())

    def is_budget_exhausted(self) -> bool:
        """True if the cumulative epsilon exceeds the target."""
        return self.epsilon_spent() >= self.target_epsilon

    @property
    def steps_taken(self) -> int:
        return self._steps_taken
