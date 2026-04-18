#!/usr/bin/env bash
# scripts/bootstrap.sh — Full FLS demo setup from zero to running.
#
# Runs all 10 steps in dependency order:
#   1.  Generate mTLS certificates
#   2.  Create k3d cluster
#   3.  Install storage layer (Redis, MinIO, PostgreSQL)
#   4.  Build Docker images (base + services + frontend + client + seed job)
#   5.  Import images into k3d
#   6.  Deploy services to k8s
#   7.  Seed model (MinIO + Redis)  ← must be BEFORE rollout-status
#   8.  Wait for rollout             ← inference-server needs seeded data to start
#   9.  Deploy monitoring stack (Prometheus + Grafana)
#   10. Start port-forwards + FL client simulators
#
# Usage:
#   bash scripts/bootstrap.sh
#   bash scripts/bootstrap.sh --skip-build   # skip Docker build (images already built)
set -euo pipefail

SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

echo "╔══════════════════════════════════════════════╗"
echo "║       FLS Demo Bootstrap                     ║"
echo "╚══════════════════════════════════════════════╝"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 1/10: Generate mTLS certificates"
# ─────────────────────────────────────────────────────────────────────────────
if [ -f infra/certs/ca.crt ]; then
  echo "    Certificates already exist — skipping."
else
  bash infra/certs/gen_certs.sh
fi

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 2/10: Create k3d cluster"
# ─────────────────────────────────────────────────────────────────────────────
bash infra/k8s/cluster-setup.sh

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 3/10: Install storage layer (Redis, MinIO, PostgreSQL)"
# ─────────────────────────────────────────────────────────────────────────────
bash infra/k8s/storage-setup.sh

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 4/10: Build Docker images"
# ─────────────────────────────────────────────────────────────────────────────
if [ "${SKIP_BUILD}" -eq 1 ]; then
  echo "    --skip-build set — skipping Docker builds."
else
  make build
  make build-services
  make build-frontend
  make build-client
  make build-seed-job
  echo "==> Exporting ONNX model for frontend..."
  make export-model
fi

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 5/10: Import images into k3d"
# ─────────────────────────────────────────────────────────────────────────────
make import-images

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 6/10: Deploy services (excluding inference-server)"
# ─────────────────────────────────────────────────────────────────────────────
# inference-server is deployed last — it tries to load the model from MinIO
# on startup and will CrashLoopBackOff if MinIO isn't seeded yet.
make deploy-services

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 7/10: Seed model (MinIO + Redis)"
# ─────────────────────────────────────────────────────────────────────────────
# Must happen BEFORE rollout-status so inference-server can start cleanly.
echo "    Waiting for Redis to be ready..."
kubectl rollout status deployment/redis -n fl-system --timeout=120s 2>/dev/null || \
  kubectl rollout status statefulset/redis-master -n fl-system --timeout=120s 2>/dev/null || true
echo "    Waiting for MinIO to be ready..."
kubectl rollout status deployment/minio -n fl-system --timeout=120s

kubectl port-forward -n fl-system svc/redis-master 6379:6379 &>/dev/null &
PF_REDIS=$!
# Use port 9002 — port 9000 is bound by k3d's loadbalancer (--port '9000:9000@loadbalancer')
kubectl port-forward -n fl-system svc/minio 9002:9000 &>/dev/null &
PF_MINIO=$!
echo "    Waiting for port-forwards to be ready..."
# Poll until both ports are actually listening (up to 60s each); fail loudly if they don't open
for port in 6379 9002; do
  ready=0
  for i in $(seq 1 60); do
    if ss -tnlp 2>/dev/null | grep -q ":${port} " || \
       nc -z localhost "${port}" 2>/dev/null; then
      echo "    Port ${port} ready."
      ready=1
      break
    fi
    sleep 1
  done
  if [ "${ready}" -eq 0 ]; then
    echo "ERROR: Port ${port} never became ready (port-forward failed?)"
    kill "${PF_REDIS}" "${PF_MINIO}" 2>/dev/null || true
    exit 1
  fi
done
REDIS_HOST=localhost MINIO_ENDPOINT=http://localhost:9002 \
  MINIO_ACCESS_KEY=flminio MINIO_SECRET_KEY=flminio123 \
  .venv/bin/python ml/training/seed_model_store.py
REDIS_HOST=localhost \
  .venv/bin/python ml/training/seed_redis.py
kill "${PF_REDIS}" "${PF_MINIO}" 2>/dev/null || true
echo "    Restarting inference-server so it picks up the seeded model..."
kubectl rollout restart deployment/inference-server -n fl-system

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 8/10: Wait for rollout"
# ─────────────────────────────────────────────────────────────────────────────
make rollout-status

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 9/10: Deploy monitoring stack (Prometheus + Grafana)"
# ─────────────────────────────────────────────────────────────────────────────
make deploy-monitoring

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 10/10: Start FL client simulators"
# ─────────────────────────────────────────────────────────────────────────────
make port-forwards
sleep 3
make up-clients-k8s

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Demo ready!                                 ║"
echo "║  Frontend:  http://localhost:3002            ║"
echo "║  MinIO:     http://localhost:9001 (Console)  ║"
echo "║  Grafana:   http://localhost:3003            ║"
echo "║  Clients:   make down-clients-k8s            ║"
echo "╚══════════════════════════════════════════════╝"
