"""
client/fl-client/agent.py

Full simulated FL client agent for the FLS federated learning system.

Lifecycle:
    Startup:
        1. Register with Client Registry (POST /clients/register) → JWT + client_id
        2. Register with gRPC Aggregation Server (RegisterClient RPC)
        3. Connect WebSocket to Push Service
        4. Load local dataset from PROFILE env var (synthetic data JSON)

    On ROUND_OPEN event:
        1. Check eligibility (simulated battery%, CPU%, privacy budget)
        2. Download model via presigned URL
        3. Run offload_policy() → TRAIN_LOCALLY or OFFLOAD
        4. If TRAIN_LOCALLY: LocalTrainer + DPEngine → SubmitUpdate gRPC
        5. If OFFLOAD: POST /offload/jobs → poll status

    On MODEL_UPDATED event:
        1. Download new model from presigned URL
        2. Hot-swap ONNX runtime session

Usage:
    PROFILE=tech CLIENT_ID=client-tech python client/fl-client/agent.py
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from typing import Optional

import grpc
import requests
import torch
import websocket  # websocket-client library

# ── Path setup ────────────────────────────────────────────────────────────────
# Project root for ml.* imports
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# This directory for sibling module imports (config, local_trainer, policy)
_CLIENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CLIENT_DIR not in sys.path:
    sys.path.insert(0, _CLIENT_DIR)

# Proto stubs — generated files use bare imports (aggregation_service_pb2)
_PROTO_DIR = os.path.join(_CLIENT_DIR, "proto_gen")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

from config import ClientConfig, load_config  # noqa: E402
from local_trainer import LocalTrainer  # noqa: E402
from policy import Decision, DeviceState, offload_policy  # noqa: E402

from ml.dp_engine.dp_engine import DPEngine  # noqa: E402

import aggregation_service_pb2 as pb2  # noqa: E402
import aggregation_service_pb2_grpc as pb2_grpc  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("fl-client")


# ── Serialization helpers (must match fedavg-engine format) ───────────────────

def serialize_delta(delta: dict[str, torch.Tensor]) -> bytes:
    """Serialize a model delta dict to gzip-compressed bytes."""
    buf = io.BytesIO()
    torch.save(delta, buf)
    return gzip.compress(buf.getvalue())


def compute_checksum(blob: bytes) -> str:
    """Compute sha256 checksum of a blob."""
    return "sha256:" + hashlib.sha256(blob).hexdigest()


# ── FL Client Agent ───────────────────────────────────────────────────────────

class FLClientAgent:
    """Simulated federated learning client."""

    def __init__(self, cfg: ClientConfig) -> None:
        self.cfg = cfg
        self.client_id = cfg.client_id
        self.jwt_token: Optional[str] = None
        self.dataset: list[dict] = []
        self.model_version: str = ""
        self.model_weights_path: str = cfg.model_weights_path
        self.onnx_session = None  # ONNX Runtime InferenceSession for inference

        # DP engine
        self.dp_engine = DPEngine(
            clip_norm=cfg.dp_clip_norm,
            noise_multiplier=cfg.dp_noise_multiplier,
            target_epsilon=cfg.dp_target_epsilon,
            target_delta=cfg.dp_target_delta,
        )

        self._shutdown = threading.Event()
        self._ws: Optional[websocket.WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._grpc_channel: Optional[grpc.Channel] = None
        self._grpc_stub: Optional[pb2_grpc.AggregationServiceStub] = None

    # ── Startup ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Execute the full startup sequence."""
        log.info("Starting FL client: id=%s profile=%s", self.cfg.client_id, self.cfg.profile)

        self._load_dataset()
        self._register_with_registry()
        self._connect_grpc()
        self._register_with_aggregation_server()
        self._connect_websocket()

        log.info("FL client ready. Waiting for round events...")
        self._wait_for_shutdown()

    def _load_dataset(self) -> None:
        """Load synthetic keystroke data for this profile."""
        path = self.cfg.dataset_path
        log.info("Loading dataset from %s", path)
        with open(path) as f:
            self.dataset = json.load(f)
        log.info("Loaded %d events for profile=%s", len(self.dataset), self.cfg.profile)

    def _register_with_registry(self) -> None:
        """POST /clients/register → get JWT + client_id."""
        url = f"{self.cfg.registry_url}/clients/register"
        payload = {
            "device_class": self.cfg.device_class,
            "caps": {
                "ram_mb": self.cfg.sim_memory_free_mb,
                "has_gpu": False,
                "cpu_cores": 4,
                "os": "linux",
                "can_train": True,
                "vocab_size_cap": 8192,
            },
        }

        for attempt in range(5):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    self.client_id = data.get("client_id", self.client_id)
                    self.jwt_token = data.get("jwt_token")
                    log.info("Registered with registry: client_id=%s", self.client_id)
                    return
                log.warning("Registry returned %d: %s", resp.status_code, resp.text)
            except requests.RequestException as e:
                log.warning("Registry request failed (attempt %d/5): %s", attempt + 1, e)
            time.sleep(2 ** attempt)

        log.error("Failed to register with client registry — continuing with default ID")

    def _connect_grpc(self) -> None:
        """Establish gRPC channel (mTLS or insecure)."""
        if self.cfg.tls_enabled and os.path.exists(self.cfg.tls_ca_cert):
            ca = open(self.cfg.tls_ca_cert, "rb").read()
            cert = open(self.cfg.tls_client_cert, "rb").read()
            key = open(self.cfg.tls_client_key, "rb").read()
            creds = grpc.ssl_channel_credentials(
                root_certificates=ca,
                private_key=key,
                certificate_chain=cert,
            )
            self._grpc_channel = grpc.secure_channel(self.cfg.agg_grpc_addr, creds)
            log.info("gRPC mTLS channel to %s", self.cfg.agg_grpc_addr)
        else:
            self._grpc_channel = grpc.insecure_channel(self.cfg.agg_grpc_addr)
            log.info("gRPC insecure channel to %s", self.cfg.agg_grpc_addr)

        self._grpc_stub = pb2_grpc.AggregationServiceStub(self._grpc_channel)

    def _register_with_aggregation_server(self) -> None:
        """RegisterClient RPC with the aggregation server."""
        req = pb2.RegisterReq(
            client_id=self.client_id,
            device_class=self.cfg.device_class,
            caps=pb2.DeviceCapabilities(
                ram_mb=self.cfg.sim_memory_free_mb,
                has_gpu=False,
                cpu_cores=4,
                os="linux",
                can_train=True,
                vocab_size_cap=8192,
            ),
        )
        try:
            resp = self._grpc_stub.RegisterClient(req, timeout=10)
            if resp.ok:
                if resp.assigned_client_id:
                    self.client_id = resp.assigned_client_id
                log.info("Registered with aggregation server: %s", self.client_id)
            else:
                log.warning("Aggregation server registration returned ok=False")
        except grpc.RpcError as e:
            log.warning("gRPC RegisterClient failed: %s — will retry on first round", e)

    def _connect_websocket(self) -> None:
        """Connect to WebSocket push service for round events."""
        ws_url = self.cfg.websocket_url
        log.info("Connecting WebSocket to %s", ws_url)

        self._ws = websocket.WebSocketApp(
            ws_url,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
            on_open=self._on_ws_open,
        )

        self._ws_thread = threading.Thread(
            target=self._ws_run_forever, daemon=True, name="ws-thread"
        )
        self._ws_thread.start()

    def _ws_run_forever(self) -> None:
        """WebSocket reconnection loop."""
        while not self._shutdown.is_set():
            try:
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                log.warning("WebSocket error: %s", e)
            if not self._shutdown.is_set():
                log.info("WebSocket disconnected — reconnecting in 5s")
                time.sleep(5)

    def _on_ws_open(self, ws) -> None:
        log.info("WebSocket connected")

    def _on_ws_error(self, ws, error) -> None:
        log.warning("WebSocket error: %s", error)

    def _on_ws_close(self, ws, close_status, close_msg) -> None:
        log.info("WebSocket closed: status=%s msg=%s", close_status, close_msg)

    def _on_ws_message(self, ws, message: str) -> None:
        """Handle incoming WebSocket messages (round events)."""
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            log.warning("Invalid JSON from WebSocket: %s", message[:200])
            return

        event_type = event.get("event", event.get("type", ""))
        log.info("Received event: %s", event_type)

        if event_type in ("ROUND_OPEN", "ROUND_OPENED"):
            threading.Thread(
                target=self._handle_round_open,
                args=(event,),
                daemon=True,
                name="round-handler",
            ).start()
        elif event_type in ("MODEL_UPDATED",):
            threading.Thread(
                target=self._handle_model_updated,
                args=(event,),
                daemon=True,
                name="model-update",
            ).start()

    # ── Round handling ────────────────────────────────────────────────────────

    def _handle_round_open(self, event: dict) -> None:
        """Handle a ROUND_OPEN event: eligibility check, train/offload, submit."""
        round_id = event.get("round_id", "")
        model_version = event.get("model_version", "")
        round_config = event.get("config", {})

        log.info("=== ROUND %s (model %s) ===", round_id, model_version)

        # 1. Check eligibility via offload policy
        device_state = DeviceState(
            battery_percent=self.cfg.sim_battery_pct,
            cpu_idle_pct=self.cfg.sim_cpu_idle_pct,
            memory_free_mb=self.cfg.sim_memory_free_mb,
            is_charging=True,
            on_wifi=True,
            model_size_bytes=16e6,
            privacy_budget_remaining=self.dp_engine.budget_remaining(),
            device_class=self.cfg.device_class,
        )

        decision = offload_policy(device_state)
        log.info("Policy decision: %s (budget_remaining=%.4f)",
                 decision.value, self.dp_engine.budget_remaining())

        if decision == Decision.SKIP:
            log.warning("Skipping round %s — privacy budget exhausted", round_id)
            return

        # 2. Download global model
        model_path = self._download_model(model_version)
        if model_path is None:
            log.error("Failed to download model — skipping round")
            return

        if decision == Decision.OFFLOAD:
            self._handle_offload(round_id, model_version)
            return

        # 3. TRAIN_LOCALLY path
        self._handle_train_locally(
            round_id=round_id,
            model_version=model_version,
            model_path=model_path,
            round_config=round_config,
        )

    def _download_model(self, model_version: str) -> Optional[str]:
        """Download model weights via GetGlobalModel RPC."""
        try:
            req = pb2.GetModelReq(model_version=model_version)
            resp = self._grpc_stub.GetGlobalModel(req, timeout=30)

            if resp.model_url:
                # Download the .pt weights via presigned URL
                # The model_url points to ONNX; we need the .pt for training
                # Construct the weights URL from the version
                weights_url = resp.model_url.replace("model_quant.onnx", "model_weights.pt")
                weights_url = weights_url.replace("model.onnx", "model_weights.pt")

                r = requests.get(weights_url, timeout=60)
                if r.status_code == 200:
                    tmp = tempfile.NamedTemporaryFile(suffix=".pt", delete=False)
                    tmp.write(r.content)
                    tmp.close()
                    self.model_version = model_version
                    log.info("Downloaded model weights: %s (%d bytes)",
                             model_version, len(r.content))
                    return tmp.name
                log.warning("Model download failed: HTTP %d", r.status_code)

        except grpc.RpcError as e:
            log.warning("GetGlobalModel RPC failed: %s", e)

        # Fallback: use local weights if available
        if os.path.exists(self.cfg.model_weights_path):
            log.info("Using local fallback model: %s", self.cfg.model_weights_path)
            return self.cfg.model_weights_path
        return None

    def _handle_train_locally(
        self,
        round_id: str,
        model_version: str,
        model_path: str,
        round_config: dict,
    ) -> None:
        """Train locally, apply DP, submit update via gRPC."""
        local_epochs = round_config.get("local_epochs", self.cfg.local_epochs)
        batch_size = round_config.get("mini_batch_size", self.cfg.batch_size)
        fedprox_mu = round_config.get("fedprox_mu", self.cfg.fedprox_mu)

        log.info("Training locally: epochs=%d batch_size=%d fedprox_mu=%.3f",
                 local_epochs, batch_size, fedprox_mu)

        t0 = time.time()

        # Train
        trainer = LocalTrainer(model_path=model_path)
        delta = trainer.train(
            dataset=self.dataset,
            local_epochs=local_epochs,
            batch_size=batch_size,
            fedprox_mu=fedprox_mu,
            learning_rate=self.cfg.learning_rate,
        )

        # Apply DP
        num_samples = len(self.dataset)
        dp_delta = self.dp_engine.clip_and_noise(delta, num_samples=num_samples)
        epsilon_spent = self.dp_engine.epsilon_spent()

        train_duration = time.time() - t0
        log.info("Training + DP complete: %.2fs, epsilon_spent=%.4f",
                 train_duration, epsilon_spent)

        # Serialize
        update_blob = serialize_delta(dp_delta)
        checksum = compute_checksum(update_blob)

        # Submit via gRPC
        self._submit_update(
            round_id=round_id,
            update_blob=update_blob,
            num_samples=num_samples,
            local_epochs=local_epochs,
            dp_epsilon=epsilon_spent,
            model_version=model_version,
            checksum=checksum,
        )

        # Emit metrics
        self._emit_metrics(
            round_id=round_id,
            train_duration=train_duration,
            samples=num_samples,
            epsilon_spent=epsilon_spent,
            offloaded=False,
        )

    def _submit_update(
        self,
        round_id: str,
        update_blob: bytes,
        num_samples: int,
        local_epochs: int,
        dp_epsilon: float,
        model_version: str,
        checksum: str,
    ) -> None:
        """Submit DP-protected delta to aggregation server via gRPC."""
        req = pb2.SubmitUpdateReq(
            round_id=round_id,
            client_id=self.client_id,
            update_blob=update_blob,
            meta=pb2.UpdateMetadata(
                num_samples=num_samples,
                local_epochs=local_epochs,
                dp_epsilon=dp_epsilon,
                dp_delta=self.cfg.dp_target_delta,
                clip_norm=self.cfg.dp_clip_norm,
                model_version=model_version,
                checksum=checksum,
                device_class=self.cfg.device_class,
                is_straggler=False,
            ),
        )

        try:
            resp = self._grpc_stub.SubmitUpdate(req, timeout=30)
            if resp.accepted:
                log.info("Update accepted for round %s", round_id)
            else:
                log.warning("Update rejected for round %s: %s", round_id, resp.reason)
        except grpc.RpcError as e:
            log.error("SubmitUpdate RPC failed: %s", e)

    def _emit_metrics(
        self,
        round_id: str,
        train_duration: float,
        samples: int,
        epsilon_spent: float,
        offloaded: bool,
    ) -> None:
        """Report telemetry to aggregation server."""
        req = pb2.MetricsReq(
            client_id=self.client_id,
            round_id=round_id,
            local_train_duration_s=train_duration,
            samples_trained=samples,
            dp_epsilon_spent=epsilon_spent,
            dp_epsilon_cumulative=self.dp_engine.epsilon_spent(),
            battery_percent=float(self.cfg.sim_battery_pct),
            offloaded=offloaded,
        )
        try:
            self._grpc_stub.EmitMetrics(req, timeout=10)
        except grpc.RpcError as e:
            log.warning("EmitMetrics failed: %s", e)

    def _handle_offload(self, round_id: str, model_version: str) -> None:
        """Offload training to the offload-worker service."""
        offload_url = self.cfg.registry_url.replace(":8081", ":8085")
        url = f"{offload_url}/offload/jobs"

        payload = {
            "client_id": self.client_id,
            "device_class": self.cfg.device_class,
            "round_id": round_id,
            "model_version": model_version,
            "num_samples": len(self.dataset),
        }

        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code != 200:
                log.error("Offload job creation failed: %d %s", resp.status_code, resp.text)
                return

            data = resp.json()
            job_id = data["job_id"]
            upload_url = data.get("upload_url")

            # Upload token batch if presigned URL provided
            if upload_url:
                token_batch = json.dumps(self.dataset).encode()
                put_resp = requests.put(upload_url, data=token_batch, timeout=30)
                if put_resp.status_code not in (200, 204):
                    log.warning("Token upload failed: %d", put_resp.status_code)

            log.info("Offload job submitted: %s", job_id)

            # Poll for completion
            self._poll_offload_status(offload_url, job_id)

        except requests.RequestException as e:
            log.error("Offload request failed: %s", e)

    def _poll_offload_status(self, base_url: str, job_id: str) -> None:
        """Poll offload job status until DONE or FAILED."""
        url = f"{base_url}/offload/jobs/{job_id}"
        for _ in range(60):
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    status = resp.json().get("status", "")
                    if status == "DONE":
                        log.info("Offload job %s completed", job_id)
                        return
                    if status == "FAILED":
                        log.error("Offload job %s failed", job_id)
                        return
            except requests.RequestException:
                pass
            time.sleep(5)

        log.warning("Offload job %s timed out after 5 minutes", job_id)

    # ── Model update handling ─────────────────────────────────────────────────

    def _handle_model_updated(self, event: dict) -> None:
        """Download new model and hot-swap ONNX session."""
        new_version = event.get("version", event.get("model_version", ""))
        log.info("Model updated notification: %s", new_version)

        try:
            req = pb2.GetModelReq(model_version=new_version)
            resp = self._grpc_stub.GetGlobalModel(req, timeout=30)

            if resp.model_url:
                # Download ONNX for inference
                r = requests.get(resp.model_url, timeout=60)
                if r.status_code == 200:
                    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
                    tmp.write(r.content)
                    tmp.close()

                    # Hot-swap ONNX session
                    try:
                        import onnxruntime as ort
                        self.onnx_session = ort.InferenceSession(tmp.name)
                        self.model_version = new_version
                        log.info("ONNX session hot-swapped to %s", new_version)
                    except ImportError:
                        log.warning("onnxruntime not available — skipping ONNX hot-swap")
                    finally:
                        os.unlink(tmp.name)

        except grpc.RpcError as e:
            log.warning("GetGlobalModel failed during model update: %s", e)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _wait_for_shutdown(self) -> None:
        """Block until SIGINT/SIGTERM."""
        def _signal_handler(signum, frame):
            log.info("Received signal %d — shutting down", signum)
            self._shutdown.set()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        self._shutdown.wait()
        self._cleanup()

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self._ws:
            self._ws.close()
        if self._grpc_channel:
            self._grpc_channel.close()
        log.info("FL client shut down")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = load_config()
    agent = FLClientAgent(cfg)
    agent.start()


if __name__ == "__main__":
    main()
