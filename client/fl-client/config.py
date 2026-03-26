"""
client/fl-client/config.py

Environment-variable-driven configuration for the simulated FL client agent.

All settings have sensible defaults for local development. In k8s they come
from the fl-common-config ConfigMap and fl-credentials Secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class ClientConfig:
    # ── Identity ──────────────────────────────────────────────────────
    client_id: str = field(default_factory=lambda: _env("CLIENT_ID", "client-tech"))
    profile: str = field(default_factory=lambda: _env("PROFILE", "tech"))
    device_class: str = field(default_factory=lambda: _env("DEVICE_CLASS", "LAPTOP_SIM"))

    # ── Cluster endpoints ─────────────────────────────────────────────
    agg_grpc_addr: str = field(
        default_factory=lambda: _env("AGG_GRPC_ADDR", "localhost:50051")
    )
    registry_url: str = field(
        default_factory=lambda: _env("REGISTRY_URL", "http://localhost:8081")
    )
    websocket_url: str = field(
        default_factory=lambda: _env("WEBSOCKET_URL", "ws://localhost:8080/ws")
    )
    inference_url: str = field(
        default_factory=lambda: _env("INFERENCE_URL", "http://localhost:8000")
    )

    # ── MinIO ─────────────────────────────────────────────────────────
    minio_endpoint: str = field(
        default_factory=lambda: _env("MINIO_ENDPOINT", "http://localhost:9000")
    )
    minio_access_key: str = field(
        default_factory=lambda: _env("MINIO_ACCESS_KEY", "flminio")
    )
    minio_secret_key: str = field(
        default_factory=lambda: _env("MINIO_SECRET_KEY", "flminio123")
    )
    minio_bucket: str = field(
        default_factory=lambda: _env("MINIO_BUCKET_MODELS", "fl-models")
    )

    # ── TLS ───────────────────────────────────────────────────────────
    tls_enabled: bool = field(
        default_factory=lambda: _env("TLS_ENABLED", "true").lower() == "true"
    )
    tls_ca_cert: str = field(
        default_factory=lambda: _env("TLS_CA_CERT", "/certs/ca.crt")
    )
    tls_client_cert: str = field(
        default_factory=lambda: _env("TLS_CLIENT_CERT", "/certs/client.crt")
    )
    tls_client_key: str = field(
        default_factory=lambda: _env("TLS_CLIENT_KEY", "/certs/client.key")
    )

    # ── Training ──────────────────────────────────────────────────────
    local_epochs: int = field(
        default_factory=lambda: int(_env("LOCAL_EPOCHS", "1"))
    )
    batch_size: int = field(
        default_factory=lambda: int(_env("BATCH_SIZE", "32"))
    )
    learning_rate: float = field(
        default_factory=lambda: float(_env("LEARNING_RATE", "1e-3"))
    )
    fedprox_mu: float = field(
        default_factory=lambda: float(_env("FEDPROX_MU", "0.01"))
    )

    # ── DP ────────────────────────────────────────────────────────────
    dp_clip_norm: float = field(
        default_factory=lambda: float(_env("DP_CLIP_NORM", "1.0"))
    )
    dp_noise_multiplier: float = field(
        default_factory=lambda: float(_env("DP_NOISE_MULTIPLIER", "1.1"))
    )
    dp_target_epsilon: float = field(
        default_factory=lambda: float(_env("DP_TARGET_EPSILON", "1.0"))
    )
    dp_target_delta: float = field(
        default_factory=lambda: float(_env("DP_TARGET_DELTA", "1e-5"))
    )

    # ── Simulated device state ────────────────────────────────────────
    sim_battery_pct: int = field(
        default_factory=lambda: int(_env("SIM_BATTERY_PCT", "85"))
    )
    sim_cpu_idle_pct: int = field(
        default_factory=lambda: int(_env("SIM_CPU_IDLE_PCT", "60"))
    )
    sim_memory_free_mb: int = field(
        default_factory=lambda: int(_env("SIM_MEMORY_FREE_MB", "2048"))
    )

    # ── Data ──────────────────────────────────────────────────────────
    data_dir: str = field(
        default_factory=lambda: _env("DATA_DIR", "/data")
    )

    # ── Model paths ───────────────────────────────────────────────────
    model_weights_path: str = field(
        default_factory=lambda: _env("MODEL_WEIGHTS_PATH", "ml/training/warmstart_final.pt")
    )

    @property
    def dataset_path(self) -> str:
        return os.path.join(self.data_dir, f"client-{self.profile}.json")


def load_config() -> ClientConfig:
    """Build a ClientConfig from current environment."""
    return ClientConfig()
