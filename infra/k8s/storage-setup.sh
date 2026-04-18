#!/usr/bin/env bash
# infra/k8s/storage-setup.sh
# Installs storage-layer dependencies (Redis, MinIO, PostgreSQL) into the
# fl-system namespace via Helm.  Idempotent — safe to re-run.
#
# Usage:
#   bash infra/k8s/storage-setup.sh           # install / upgrade all
#   bash infra/k8s/storage-setup.sh redis     # redis only
#   bash infra/k8s/storage-setup.sh minio     # minio only
#   bash infra/k8s/storage-setup.sh postgres  # postgres only
#
# Prerequisites:
#   - k3d cluster running  (bash infra/k8s/cluster-setup.sh)
#   - helm >= 3.x
#   - bitnami repo added   (script adds it automatically)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

NS="fl-system"

# ── Dependency checks ─────────────────────────────────────────────────────────
for cmd in helm kubectl; do
    if ! command -v "${cmd}" &>/dev/null; then
        echo "ERROR: '${cmd}' not found in PATH." >&2
        exit 1
    fi
done

# ── Helm repos ────────────────────────────────────────────────────────────────
# Bitnami: used for Redis and PostgreSQL.
# MinIO official: used for MinIO — Bitnami stopped publishing images to Docker
# Hub in 2024, so docker.io/bitnami/minio no longer exists.  The official chart
# (charts.min.io) uses quay.io/minio/minio which is reliably available.
if ! helm repo list 2>/dev/null | grep -q "^bitnami"; then
    echo "==> Adding Bitnami Helm repo..."
    helm repo add bitnami https://charts.bitnami.com/bitnami
fi
if ! helm repo list 2>/dev/null | grep -q "^minio-official"; then
    echo "==> Adding MinIO official Helm repo..."
    helm repo add minio-official https://charts.min.io/
fi
helm repo update bitnami minio-official --fail-on-repo-update-fail

TARGET="${1:-all}"

# ─────────────────────────────────────────────────────────────────────────────
# Redis
# ─────────────────────────────────────────────────────────────────────────────
install_redis() {
    echo ""
    echo "==> Installing / upgrading Redis in namespace '${NS}'..."
    local redis_config
    redis_config=$'maxmemory 200mb\nmaxmemory-policy allkeys-lru'
    helm upgrade --install redis bitnami/redis \
        --namespace "${NS}" \
        --set auth.enabled=false \
        --set master.resources.limits.memory=256Mi \
        --set master.resources.requests.memory=128Mi \
        --set master.resources.limits.cpu=500m \
        --set master.resources.requests.cpu=100m \
        --set master.persistence.enabled=true \
        --set master.persistence.size=1Gi \
        --set replica.replicaCount=0 \
        --set-string master.configuration="${redis_config}" \
        --wait --timeout=120s
    echo "    Redis OK"
}

# ─────────────────────────────────────────────────────────────────────────────
# MinIO
# ─────────────────────────────────────────────────────────────────────────────
install_minio() {
    echo ""
    echo "==> Installing / upgrading MinIO in namespace '${NS}'..."
    # Chart: minio-official/minio v5.4.0 (quay.io/minio/minio — not bitnami).
    # Bitnami's chart is unusable because docker.io/bitnami/minio no longer
    # exists on Docker Hub (Bitnami removed all images in 2024).
    helm upgrade --install minio minio-official/minio \
        --namespace "${NS}" \
        --version 5.4.0 \
        --set rootUser=flminio \
        --set rootPassword=flminio123 \
        --set mode=standalone \
        --set "resources.requests.memory=128Mi" \
        --set "resources.limits.memory=256Mi" \
        --set "resources.requests.cpu=100m" \
        --set "resources.limits.cpu=500m" \
        --set persistence.enabled=true \
        --set persistence.size=10Gi \
        --wait --timeout=180s
    echo "    MinIO OK"
    echo ""
    echo "==> Applying MinIO bucket init job..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # Delete any previous run so re-apply actually creates a fresh Job.
    # (kubectl apply on a completed Job is a no-op — it won't re-execute.)
    kubectl delete job minio-bucket-init --namespace "${NS}" --ignore-not-found=true
    kubectl apply -f "${SCRIPT_DIR}/minio-init-job.yaml"
    echo "    Waiting for bucket init job to complete (timeout 120s)..."
    kubectl wait job/minio-bucket-init \
        --namespace "${NS}" \
        --for=condition=complete \
        --timeout=120s \
        && echo "    Buckets initialised." \
        || { echo "    WARNING: init job did not complete — check: kubectl logs -n ${NS} -l job-name=minio-bucket-init"; }
}

# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL
# ─────────────────────────────────────────────────────────────────────────────
install_postgres() {
    echo ""
    echo "==> Installing / upgrading PostgreSQL in namespace '${NS}'..."
    helm upgrade --install postgresql bitnami/postgresql \
        --namespace "${NS}" \
        --set auth.postgresPassword=flpg123 \
        --set auth.database=fl_registry \
        --set primary.resources.limits.memory=256Mi \
        --set primary.resources.requests.memory=128Mi \
        --set primary.resources.limits.cpu=500m \
        --set primary.resources.requests.cpu=100m \
        --set primary.persistence.enabled=true \
        --set primary.persistence.size=2Gi \
        --set readReplicas.replicaCount=0 \
        --wait --timeout=120s
    echo "    PostgreSQL OK"

    echo ""
    echo "==> Applying database migrations..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    MIGRATIONS_DIR="${SCRIPT_DIR}/../../services/client-registry/migrations"
    if [[ -d "${MIGRATIONS_DIR}" ]]; then
        for sql_file in "${MIGRATIONS_DIR}"/*.sql; do
            [[ -f "${sql_file}" ]] || continue
            echo "    Applying $(basename "${sql_file}")..."
            kubectl exec -i -n "${NS}" svc/postgresql -- \
                env PGPASSWORD=flpg123 psql -U postgres -d fl_registry < "${sql_file}"
        done
        echo "    Migrations applied."
    else
        echo "    WARNING: migrations dir not found at ${MIGRATIONS_DIR}"
    fi
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "${TARGET}" in
    redis)    install_redis ;;
    minio)    install_minio ;;
    postgres) install_postgres ;;
    all)
        install_redis
        install_minio
        install_postgres
        ;;
    *)
        echo "ERROR: unknown target '${TARGET}'. Use: redis | minio | postgres | all" >&2
        exit 1
        ;;
esac

echo ""
echo "==> Storage layer ready.  Running pods in '${NS}':"
kubectl get pods -n "${NS}"
echo ""
echo "    Verify Redis:"
echo "      kubectl wait pod -l app.kubernetes.io/name=redis -n ${NS} --for=condition=Ready --timeout=120s"
echo "      kubectl exec -n ${NS} deploy/redis-master -- redis-cli ping"
