"""
client/fl-client/policy.py

Offload policy from system design Section 13.

Determines whether a client should TRAIN_LOCALLY or OFFLOAD to the
offload-worker service based on simulated device state.

Decision tree:
    ESP32                              → OFFLOAD (always)
    Privacy budget exhausted           → SKIP
    Battery < 20% and not charging     → OFFLOAD
    Memory < 500 MB                    → OFFLOAD
    CPU idle < 30%                     → OFFLOAD
    Not on WiFi                        → OFFLOAD
    Otherwise                          → TRAIN_LOCALLY
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(Enum):
    TRAIN_LOCALLY = "TRAIN_LOCALLY"
    OFFLOAD = "OFFLOAD"
    SKIP = "SKIP"


@dataclass
class DeviceState:
    battery_percent: float
    cpu_idle_pct: float
    memory_free_mb: float
    is_charging: bool
    on_wifi: bool
    model_size_bytes: float
    privacy_budget_remaining: float
    device_class: str  # LAPTOP_SIM | ANDROID | ESP32


# ── Thresholds ────────────────────────────────────────────────────────────────

BATTERY_MIN = 20        # percent
MEMORY_MIN_MB = 500     # MB free RAM
CPU_IDLE_MIN = 30       # percent idle
BUDGET_EPSILON_MIN = 0.01  # below this, budget is exhausted


def offload_policy(state: DeviceState) -> Decision:
    """
    Evaluate device state and return a training decision.

    This is the client-side eligibility + offload check described in
    system design Section 13.
    """
    # ESP32 devices can never train locally
    if state.device_class == "ESP32":
        return Decision.OFFLOAD

    # If privacy budget is exhausted, skip this round entirely
    if state.privacy_budget_remaining < BUDGET_EPSILON_MIN:
        return Decision.SKIP

    # Resource checks — offload if device is constrained
    if state.battery_percent < BATTERY_MIN and not state.is_charging:
        return Decision.OFFLOAD

    if state.memory_free_mb < MEMORY_MIN_MB:
        return Decision.OFFLOAD

    if state.cpu_idle_pct < CPU_IDLE_MIN:
        return Decision.OFFLOAD

    if not state.on_wifi:
        return Decision.OFFLOAD

    return Decision.TRAIN_LOCALLY
