#!/usr/bin/env bash
# scripts/teardown.sh — Stop the FLS demo cleanly.
#
# What this does:
#   1. Stop FL client simulators (Docker Compose)
#   2. Kill all kubectl port-forwards
#   3. Delete the k3d cluster (removes all k8s workloads + containerd images)
#   4. Optionally prune stopped Docker containers and dangling images
#
# What this does NOT do:
#   - Delete built Docker images (fl-base-python, service images, fl-client, etc.)
#     so the next bootstrap can use --skip-build and save 20-40 min of rebuild time.
#   - Run docker system prune -a (use that only when you also want to force a full rebuild)
#
# Usage:
#   bash scripts/teardown.sh           # stop everything, keep built images
#   bash scripts/teardown.sh --prune   # also prune stopped containers + dangling images
set -euo pipefail

PRUNE=0
for arg in "$@"; do
  case "$arg" in
    --prune) PRUNE=1 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

echo "╔══════════════════════════════════════════════╗"
echo "║       FLS Demo Teardown                      ║"
echo "╚══════════════════════════════════════════════╝"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT}"

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 1/4: Stop FL client simulators"
# ─────────────────────────────────────────────────────────────────────────────
if docker compose -f infra/docker-compose.clients-k8s.yml ps -q 2>/dev/null | grep -q .; then
  docker compose -f infra/docker-compose.clients-k8s.yml down
  echo "    Clients stopped."
else
  echo "    No clients running — skipping."
fi

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 2/4: Kill kubectl port-forwards"
# ─────────────────────────────────────────────────────────────────────────────
# fuser -k kills by port — safe, never matches its own parent shell
# (pkill -f would self-terminate because make's shell cmdline contains the pattern)
fuser -k -TERM \
  50052/tcp 8083/tcp 8090/tcp 8001/tcp 8091/tcp 8085/tcp \
  9002/tcp 9001/tcp 6379/tcp 3002/tcp 3003/tcp \
  2>/dev/null || true
echo "    Port-forwards cleared."

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 3/4: Delete k3d cluster"
# ─────────────────────────────────────────────────────────────────────────────
CLUSTER="fl-demo"
if k3d cluster list 2>/dev/null | grep -q "^${CLUSTER}"; then
  bash infra/k8s/cluster-setup.sh --delete
  echo "    Cluster '${CLUSTER}' deleted."
else
  echo "    Cluster '${CLUSTER}' not found — skipping."
fi

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Step 4/4: Docker cleanup"
# ─────────────────────────────────────────────────────────────────────────────
if [ "${PRUNE}" -eq 1 ]; then
  echo "    --prune set: removing stopped containers and dangling images..."
  docker container prune -f
  docker image prune -f
  echo "    Docker pruned."
else
  echo "    Skipping Docker prune (built images preserved)."
  echo "    Run with --prune to also remove stopped containers + dangling images."
  echo "    Run 'docker system prune -a --volumes' for a full clean slate (forces full rebuild)."
fi

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Teardown complete.                          ║"
echo "║  To restart:                                 ║"
echo "║    bash scripts/bootstrap.sh --skip-build    ║"
echo "╚══════════════════════════════════════════════╝"
