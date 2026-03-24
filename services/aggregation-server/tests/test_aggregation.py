"""
services/aggregation-server/tests/test_aggregation.py

Integration tests for the gRPC Aggregation Server.

Usage:
    # Start the aggregation-server first, then:
    cd services/aggregation-server/tests
    python test_aggregation.py

Prerequisites:
    - aggregation-server running on localhost:50051 with mTLS
    - Redis and MinIO accessible (port-forwarded or local)
    - Certs generated (bash infra/certs/gen_certs.sh)
    - Model seeded in MinIO + Redis (python ml/training/seed_model_store.py)
"""

from __future__ import annotations

import hashlib
import gzip
import os
import sys
from pathlib import Path

import grpc

# Resolve paths
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_TESTS_DIR / "proto_gen"))

from proto_gen import aggregation_service_pb2 as pb
from proto_gen import aggregation_service_pb2_grpc as grpc_stub

# ── Config ───────────────────────────────────────────────────────────────────
GRPC_ADDR = os.environ.get("GRPC_ADDR", "localhost:50051")
CERTS_DIR = _REPO_ROOT / "infra" / "certs"

# ── Channel setup ────────────────────────────────────────────────────────────

def make_secure_channel():
    """Create an mTLS gRPC channel using client-tech certs."""
    client_cert = (CERTS_DIR / "client-tech.crt").read_bytes()
    client_key = (CERTS_DIR / "client-tech.key").read_bytes()
    ca_cert = (CERTS_DIR / "ca.crt").read_bytes()

    creds = grpc.ssl_channel_credentials(ca_cert, client_key, client_cert)
    return grpc.secure_channel(GRPC_ADDR, creds)


def make_insecure_channel():
    """Create a plain (no TLS) gRPC channel."""
    return grpc.insecure_channel(GRPC_ADDR)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_register_client():
    """Test 1: Register a client via gRPC → client-registry."""
    channel = make_secure_channel()
    stub = grpc_stub.AggregationServiceStub(channel)

    resp = stub.RegisterClient(pb.RegisterReq(
        client_id="test-client-001",
        device_class="LAPTOP_SIM",
        caps=pb.DeviceCapabilities(
            ram_mb=400, has_gpu=False, cpu_cores=1,
            os="linux", can_train=True, vocab_size_cap=8192,
        ),
    ))
    assert resp.ok, f"registration failed: {resp}"
    assert resp.assigned_client_id, "no assigned_client_id"
    print(f"Registered: {resp.assigned_client_id}")
    channel.close()
    return resp.assigned_client_id


def test_get_global_model():
    """Test 2: Get global model metadata + presigned URL."""
    channel = make_secure_channel()
    stub = grpc_stub.AggregationServiceStub(channel)

    resp = stub.GetGlobalModel(pb.GetModelReq(model_version="v1.0.0"))
    assert resp.model_url.startswith("http"), f"no model URL: {resp.model_url}"
    print(f"Model URL: {resp.model_url[:80]}...")
    if resp.vocab_url:
        print(f"Vocab URL: {resp.vocab_url[:80]}...")
    channel.close()


def test_submit_update():
    """Test 3: Submit a mock update blob."""
    channel = make_secure_channel()
    stub = grpc_stub.AggregationServiceStub(channel)

    delta = gzip.compress(b'\x00' * 1000)
    checksum = "sha256:" + hashlib.sha256(delta).hexdigest()

    resp = stub.SubmitUpdate(pb.SubmitUpdateReq(
        round_id="round-test-001",
        client_id="test-client-001",
        update_blob=delta,
        meta=pb.UpdateMetadata(
            num_samples=100, local_epochs=1,
            dp_epsilon=0.8, dp_delta=1e-5, clip_norm=1.0,
            model_version="v1.0.0", checksum=checksum,
            device_class="LAPTOP_SIM",
        ),
    ))
    print(f"SubmitUpdate accepted: {resp.accepted}, reason: {resp.reason}")
    # May be rejected if no round is open — that's OK; test it doesn't crash
    channel.close()
    return resp


def test_duplicate_submission():
    """Test 4: Duplicate submission should be rejected."""
    channel = make_secure_channel()
    stub = grpc_stub.AggregationServiceStub(channel)

    delta = gzip.compress(b'\x00' * 1000)
    checksum = "sha256:" + hashlib.sha256(delta).hexdigest()

    # Second submission with same round_id + client_id
    resp = stub.SubmitUpdate(pb.SubmitUpdateReq(
        round_id="round-test-001",
        client_id="test-client-001",
        update_blob=delta,
        meta=pb.UpdateMetadata(
            num_samples=100, local_epochs=1,
            dp_epsilon=0.8, dp_delta=1e-5, clip_norm=1.0,
            model_version="v1.0.0", checksum=checksum,
            device_class="LAPTOP_SIM",
        ),
    ))
    assert not resp.accepted or resp.reason == "duplicate", \
        f"duplicate should be rejected, got: accepted={resp.accepted}, reason={resp.reason}"
    print(f"Duplicate correctly handled: accepted={resp.accepted}, reason={resp.reason}")
    channel.close()


def test_mtls_required():
    """Test 5: Plain (insecure) channel should be rejected."""
    channel = make_insecure_channel()
    stub = grpc_stub.AggregationServiceStub(channel)

    try:
        stub.GetGlobalModel(pb.GetModelReq(model_version="v1.0.0"), timeout=3)
        assert False, "plain channel should be rejected"
    except grpc.RpcError as e:
        print(f"Plain channel correctly rejected: {e.code()}")
    finally:
        channel.close()


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_register_client()
    print("[PASS] RegisterClient")

    test_get_global_model()
    print("[PASS] GetGlobalModel")

    resp = test_submit_update()
    print("[PASS] SubmitUpdate (no crash)")

    test_duplicate_submission()
    print("[PASS] Duplicate rejection")

    test_mtls_required()
    print("[PASS] mTLS enforcement")

    print("\nALL AGGREGATION SERVER TESTS PASSED")
