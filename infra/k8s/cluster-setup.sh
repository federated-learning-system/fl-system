#!/usr/bin/env bash
# infra/k8s/cluster-setup.sh
# Idempotent k3d cluster creation for the FLS federated learning demo.
#
# Usage:
#   bash infra/k8s/cluster-setup.sh          # create cluster + namespaces
#   bash infra/k8s/cluster-setup.sh --delete # tear down the cluster
#
# Requirements: k3d >= 5.x, kubectl
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CLUSTER_NAME="fl-demo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACES_YAML="${SCRIPT_DIR}/namespaces.yaml"

# ── Delete flag ───────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--delete" ]]; then
    echo "==> Deleting k3d cluster '${CLUSTER_NAME}'..."
    k3d cluster delete "${CLUSTER_NAME}"
    # Remove the Docker network too — k3d leaves it behind and stale state
    # causes the next cluster creation to race-crash on this kernel.
    docker network rm "k3d-${CLUSTER_NAME}" 2>/dev/null || true
    echo "    Done."
    exit 0
fi

# ── Check dependencies ────────────────────────────────────────────────────────
for cmd in k3d kubectl; do
    if ! command -v "${cmd}" &>/dev/null; then
        echo "ERROR: '${cmd}' not found in PATH. Please install it first." >&2
        exit 1
    fi
done

# ── Create cluster (idempotent) ───────────────────────────────────────────────
if k3d cluster list 2>/dev/null | grep -q "^${CLUSTER_NAME}"; then
    echo "==> Cluster '${CLUSTER_NAME}' already exists — skipping creation."
else
    # Purge any leftover Docker network from a previous failed/deleted run.
    # On this kernel (Arch Linux, nf_tables-only) a stale network causes k3s
    # to crash with 'procReady not received' during CoreDNS injection.
    if docker network inspect "k3d-${CLUSTER_NAME}" &>/dev/null; then
        echo "==> Removing stale Docker network 'k3d-${CLUSTER_NAME}'..."
        docker network rm "k3d-${CLUSTER_NAME}" 2>/dev/null || true
    fi

    echo "==> Creating k3d cluster '${CLUSTER_NAME}'..."
    k3d cluster create "${CLUSTER_NAME}" \
        --agents 2 \
        --port "3000:3000@loadbalancer" \
        --port "8000:8000@loadbalancer" \
        --port "8080:8080@loadbalancer" \
        --port "8081:8081@loadbalancer" \
        --port "8082:8082@loadbalancer" \
        --port "9090:9090@loadbalancer" \
        --port "50051:50051@loadbalancer" \
        --port "9000:9000@loadbalancer" \
        --port "3001:3001@loadbalancer" \
        --k3s-arg "--disable=traefik@server:0" \
        --k3s-arg "--disable=servicelb@server:0" \
        --k3s-arg "--disable-network-policy@server:0" \
        --k3s-arg "--flannel-backend=host-gw@server:0"
    echo "    Cluster created."
fi

# ── Ensure kubeconfig is current ──────────────────────────────────────────────
echo "==> Merging kubeconfig for '${CLUSTER_NAME}'..."
k3d kubeconfig merge "${CLUSTER_NAME}" --kubeconfig-switch-context

# ── Wait for API server to accept connections ─────────────────────────────────
echo "==> Waiting for API server to become reachable (timeout 60s)..."
API_TIMEOUT=60
API_ELAPSED=0
until kubectl cluster-info &>/dev/null; do
    if [[ ${API_ELAPSED} -ge ${API_TIMEOUT} ]]; then
        echo "ERROR: API server did not become reachable within ${API_TIMEOUT}s" >&2
        exit 1
    fi
    sleep 2
    API_ELAPSED=$(( API_ELAPSED + 2 ))
done
echo "    API server is up."

# ── Wait for nodes to be Ready ────────────────────────────────────────────────
echo "==> Waiting for all nodes to be Ready (timeout 90s)..."
kubectl wait node \
    --all \
    --for=condition=Ready \
    --timeout=90s

echo ""
kubectl get nodes
echo ""

# ── Wait for API server to be fully ready (admit resource requests) ──────────
echo "==> Waiting for API server to handle resource requests..."
ADMIT_TIMEOUT=60
ADMIT_ELAPSED=0
until kubectl get ns kube-system &>/dev/null; do
    if [[ ${ADMIT_ELAPSED} -ge ${ADMIT_TIMEOUT} ]]; then
        echo "ERROR: API server did not become fully ready within ${ADMIT_TIMEOUT}s" >&2
        exit 1
    fi
    sleep 2
    ADMIT_ELAPSED=$(( ADMIT_ELAPSED + 2 ))
done

# ── Apply namespace manifests (idempotent via server-side apply) ──────────────
echo "==> Applying namespace and quota manifests..."
kubectl apply -f "${NAMESPACES_YAML}"

echo ""
echo "==> Verifying namespaces..."
kubectl get ns fl-system fl-monitoring

echo ""
echo "==> Cluster '${CLUSTER_NAME}' is ready."
echo ""
echo "    Quick checks:"
echo "      kubectl get nodes"
echo "      kubectl get ns fl-system fl-monitoring"
echo "      kubectl describe resourcequota -n fl-system"
echo "      kubectl describe resourcequota -n fl-monitoring"
