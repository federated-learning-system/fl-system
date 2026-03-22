"""
services/shared/minio_client.py

Shared MinIO/S3 client for all FLS Python services.

Features:
  - boto3 client pointed at the in-cluster MinIO endpoint
  - Presigned URL generation (GET + PUT) for large blob transfers
  - Model blob upload helper that returns the S3 key
  - Module-level singleton — call get_client() to obtain the shared instance

Usage:
    from services.shared.minio_client import get_client, upload_model_blob
    from services.shared.minio_client import get_presigned_download_url

    key = upload_model_blob("/tmp/model.onnx", version="v1")
    url = get_presigned_download_url(BUCKET_MODELS, key)

Environment variables:
    MINIO_ENDPOINT        default: http://minio:9000
    MINIO_ACCESS_KEY      default: flminio
    MINIO_SECRET_KEY      default: flminio123
    MINIO_BUCKET_MODELS   default: fl-models
    MINIO_BUCKET_OFFLOAD  default: fl-offload
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "flminio")
_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "flminio123")

BUCKET_MODELS = os.environ.get("MINIO_BUCKET_MODELS", "fl-models")
BUCKET_OFFLOAD = os.environ.get("MINIO_BUCKET_OFFLOAD", "fl-offload")

# Module-level singleton
_client: Optional[boto3.client] = None  # type: ignore[type-arg]


# ── Client factory ────────────────────────────────────────────────────────────

def get_client() -> boto3.client:  # type: ignore[type-arg]
    """
    Return the module-level boto3 S3 client pointed at MinIO.

    The client is created once and reused.  Thread-safe for reads; callers
    that mutate module state should guard with a lock if needed.
    """
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
            # Path-style addressing required for MinIO.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            region_name="us-east-1",  # dummy region; MinIO ignores it
        )
        log.info("MinIO client initialised: endpoint=%s", _ENDPOINT)
    return _client


# ── Presigned URLs ─────────────────────────────────────────────────────────────

def get_presigned_download_url(bucket: str, key: str, expiry_seconds: int = 600) -> str:
    """
    Generate a presigned GET URL for *key* in *bucket*.

    Default expiry is 10 minutes (matching the system design spec).
    Clients use this URL to stream model blobs without going through gRPC.
    """
    url: str = get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry_seconds,
    )
    log.debug("Presigned GET %s/%s (ttl=%ds)", bucket, key, expiry_seconds)
    return url


def get_presigned_upload_url(bucket: str, key: str, expiry_seconds: int = 600) -> str:
    """
    Generate a presigned PUT URL for *key* in *bucket*.

    FL clients (or the offload worker) use this to upload delta blobs
    directly to MinIO, bypassing the aggregation server for large payloads.
    """
    url: str = get_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry_seconds,
    )
    log.debug("Presigned PUT %s/%s (ttl=%ds)", bucket, key, expiry_seconds)
    return url


# ── Model blob helpers ────────────────────────────────────────────────────────

def upload_model_blob(local_path: str, version: str, filename: str | None = None) -> str:
    """
    Upload a model file to ``fl-models/models/{version}/{filename}``.

    *filename* defaults to the basename of *local_path*.
    Returns the S3 key so callers can store it in Redis.

    Example:
        key = upload_model_blob("/tmp/model.onnx", version="v1")
        # → "models/v1/model.onnx"
    """
    if filename is None:
        filename = os.path.basename(local_path)

    key = f"models/{version}/{filename}"
    get_client().upload_file(local_path, BUCKET_MODELS, key)
    log.info("Uploaded %s → s3://%s/%s", local_path, BUCKET_MODELS, key)
    return key


def upload_update_blob(local_path: str, round_id: str, client_id: str) -> str:
    """
    Upload a client delta blob to ``fl-models/updates/{round_id}/{client_id}.delta.gz``.

    Returns the S3 key.  Blobs under ``updates/`` are auto-deleted after 48 h
    by the MinIO lifecycle rule set in minio-init-job.yaml.
    """
    key = f"updates/{round_id}/{client_id}.delta.gz"
    get_client().upload_file(local_path, BUCKET_MODELS, key)
    log.info("Uploaded delta %s → s3://%s/%s", local_path, BUCKET_MODELS, key)
    return key


def download_blob(bucket: str, key: str, local_path: str) -> None:
    """Download *key* from *bucket* to *local_path*."""
    get_client().download_file(bucket, key, local_path)
    log.info("Downloaded s3://%s/%s → %s", bucket, key, local_path)


def object_exists(bucket: str, key: str) -> bool:
    """Return True if *key* exists in *bucket*, False otherwise."""
    try:
        get_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise
