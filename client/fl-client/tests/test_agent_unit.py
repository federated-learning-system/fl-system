"""
client/fl-client/tests/test_agent_unit.py

Unit tests for FL client agent components: LocalTrainer, DPEngine, offload policy.

Run from project root:
    .venv/bin/python client/fl-client/tests/test_agent_unit.py
"""

import os
import sys

# Path setup — project root for ml.* imports, client dir for sibling modules
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_CLIENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (_PROJECT_ROOT, _CLIENT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import torch
from local_trainer import LocalTrainer
from ml.dp_engine.dp_engine import DPEngine
from policy import offload_policy, DeviceState, Decision


def test_local_trainer_produces_delta():
    """Test 1: Local trainer produces delta of correct shape."""
    model_path = os.path.join(_PROJECT_ROOT, "ml", "training", "warmstart_final.pt")
    assert os.path.exists(model_path), f"Model not found: {model_path}"

    trainer = LocalTrainer(model_path=model_path)

    # Build fake data matching the synthetic data format:
    # {"token_id": int, "context_ids": [int x10], "timestamp_ms": int}
    fake_data = [
        {
            "token_id": i % 8192,
            "context_ids": [(i * 7 + j) % 8192 for j in range(10)],
            "timestamp_ms": 1700000000000 + i * 100,
        }
        for i in range(100)
    ]

    delta = trainer.train(
        fake_data,
        local_epochs=1,
        batch_size=32,
        global_model_path=model_path,
        fedprox_mu=0.01,
    )

    assert isinstance(delta, dict), "delta must be dict of tensors"
    for k, v in delta.items():
        assert isinstance(v, torch.Tensor), f"delta[{k}] not a tensor"

    # Verify expected parameter keys are present
    expected_keys = {"embedding.weight", "lstm.weight_ih_l0", "output.weight", "output.bias"}
    assert expected_keys.issubset(delta.keys()), (
        f"Missing keys: {expected_keys - delta.keys()}"
    )

    # Verify shapes match the model architecture
    assert delta["embedding.weight"].shape == torch.Size([8192, 128])
    assert delta["output.weight"].shape == torch.Size([8192, 256])
    assert delta["output.bias"].shape == torch.Size([8192])

    # Delta should be non-zero (training actually moved weights)
    emb_norm = torch.norm(delta["embedding.weight"]).item()
    assert emb_norm > 0, "Delta embedding norm should be > 0 after training"

    print(f"Delta keys: {list(delta.keys())[:3]}")
    print(f"Delta embedding norm: {emb_norm:.4f}")
    print("TEST 1 PASSED: Local trainer produces delta of correct shape")


def test_dp_engine_clips_and_noises():
    """Test 1b: DPEngine applies clipping and noise to delta."""
    dp = DPEngine(clip_norm=1.0, noise_multiplier=1.1,
                  target_epsilon=1.0, target_delta=1e-5)

    # Fake delta with large norm to test clipping
    fake_delta = {
        "embedding.weight": torch.randn(8192, 128) * 10,  # large norm
        "output.bias": torch.randn(8192) * 5,
    }

    noised = dp.clip_and_noise(fake_delta, num_samples=100)

    assert set(noised.keys()) == set(fake_delta.keys())
    for k in noised:
        assert noised[k].shape == fake_delta[k].shape

    # Each layer should have been clipped to norm <= clip_norm (before noise)
    # After noise, norm may exceed clip_norm, but it should differ from original
    for k in noised:
        assert not torch.equal(noised[k], fake_delta[k]), f"DP should modify {k}"

    assert dp.steps_taken == 1
    assert dp.epsilon_spent() > 0

    print(f"Epsilon spent after 1 step: {dp.epsilon_spent():.6f}")
    print("TEST 1b PASSED: DPEngine clips and noises delta correctly")


def test_policy_train_locally():
    """Test 2: Policy returns TRAIN_LOCALLY when conditions good."""
    state_good = DeviceState(
        battery_percent=90,
        cpu_idle_pct=70,
        memory_free_mb=2000,
        is_charging=True,
        on_wifi=True,
        model_size_bytes=12e6,
        privacy_budget_remaining=8.0,
        device_class="LAPTOP_SIM",
    )
    assert offload_policy(state_good) == Decision.TRAIN_LOCALLY
    print("TEST 2 PASSED: Policy returns TRAIN_LOCALLY when conditions good")


def test_policy_offload_low_battery():
    """Test 3: Policy returns OFFLOAD when battery low."""
    state_low_bat = DeviceState(
        battery_percent=10,
        cpu_idle_pct=70,
        memory_free_mb=2000,
        is_charging=False,
        on_wifi=True,
        model_size_bytes=12e6,
        privacy_budget_remaining=8.0,
        device_class="LAPTOP_SIM",
    )
    assert offload_policy(state_low_bat) == Decision.OFFLOAD
    print("TEST 3 PASSED: Policy returns OFFLOAD when battery low")


def test_policy_esp32_always_offloads():
    """Test 4: ESP32 always offloads."""
    state_esp32 = DeviceState(
        battery_percent=90,
        cpu_idle_pct=70,
        memory_free_mb=100,
        is_charging=True,
        on_wifi=True,
        model_size_bytes=0,
        privacy_budget_remaining=8.0,
        device_class="ESP32",
    )
    assert offload_policy(state_esp32) == Decision.OFFLOAD, "ESP32 must always offload"
    print("TEST 4 PASSED: ESP32 always offloads")


def test_policy_budget_exhausted():
    """Test 5: Policy returns SKIP when privacy budget exhausted."""
    state_no_budget = DeviceState(
        battery_percent=90,
        cpu_idle_pct=70,
        memory_free_mb=2000,
        is_charging=True,
        on_wifi=True,
        model_size_bytes=12e6,
        privacy_budget_remaining=0.001,
        device_class="LAPTOP_SIM",
    )
    assert offload_policy(state_no_budget) == Decision.SKIP
    print("TEST 5 PASSED: Policy returns SKIP when budget exhausted")


def test_policy_low_memory_offloads():
    """Test 6: Policy returns OFFLOAD when memory low."""
    state_low_mem = DeviceState(
        battery_percent=90,
        cpu_idle_pct=70,
        memory_free_mb=200,
        is_charging=True,
        on_wifi=True,
        model_size_bytes=12e6,
        privacy_budget_remaining=8.0,
        device_class="LAPTOP_SIM",
    )
    assert offload_policy(state_low_mem) == Decision.OFFLOAD
    print("TEST 6 PASSED: Policy returns OFFLOAD when memory low")


def test_policy_no_wifi_offloads():
    """Test 7: Policy returns OFFLOAD when not on WiFi."""
    state_no_wifi = DeviceState(
        battery_percent=90,
        cpu_idle_pct=70,
        memory_free_mb=2000,
        is_charging=True,
        on_wifi=False,
        model_size_bytes=12e6,
        privacy_budget_remaining=8.0,
        device_class="LAPTOP_SIM",
    )
    assert offload_policy(state_no_wifi) == Decision.OFFLOAD
    print("TEST 7 PASSED: Policy returns OFFLOAD when not on WiFi")


if __name__ == "__main__":
    print("=" * 60)
    print("FL Client Agent Unit Tests")
    print("=" * 60)

    test_local_trainer_produces_delta()
    test_dp_engine_clips_and_noises()
    test_policy_train_locally()
    test_policy_offload_low_battery()
    test_policy_esp32_always_offloads()
    test_policy_budget_exhausted()
    test_policy_low_memory_offloads()
    test_policy_no_wifi_offloads()

    print("=" * 60)
    print("ALL CLIENT AGENT UNIT TESTS PASSED")
    print("=" * 60)
