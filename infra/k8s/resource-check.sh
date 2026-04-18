#!/usr/bin/env bash
# infra/k8s/resource-check.sh
#
# Reports actual memory and CPU usage per pod in fl-system namespace.
# Requires: kubectl with metrics-server installed (k3d bundles it).
#
# Usage:
#   bash infra/k8s/resource-check.sh            # all pods in fl-system
#   bash infra/k8s/resource-check.sh fl-monitoring  # override namespace
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

NS="${1:-fl-system}"

if ! command -v kubectl &>/dev/null; then
    echo "ERROR: kubectl not found in PATH." >&2
    exit 1
fi

echo "=========================================="
echo "  Resource Usage Report — namespace: ${NS}"
echo "  $(date -Iseconds)"
echo "=========================================="
echo ""

# ── Pod-level memory and CPU ─────────────────────────────────────────────────
echo "--- Pod Memory & CPU (from metrics-server) ---"
echo ""
if kubectl top pods -n "${NS}" 2>/dev/null; then
    true
else
    echo "WARNING: metrics-server not available or no pods running."
    echo "         Install metrics-server or check 'kubectl top pods -n ${NS}' manually."
fi

echo ""

# ── Resource requests vs limits vs actual ────────────────────────────────────
echo "--- Resource Requests / Limits (from pod specs) ---"
echo ""
printf "%-30s  %-12s %-12s  %-12s %-12s\n" "POD" "MEM_REQ" "MEM_LIM" "CPU_REQ" "CPU_LIM"
printf "%-30s  %-12s %-12s  %-12s %-12s\n" "---" "-------" "-------" "-------" "-------"

kubectl get pods -n "${NS}" -o json | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
for pod in data.get('items', []):
    name = pod['metadata']['name'][:30]
    for c in pod['spec']['containers']:
        res = c.get('resources', {})
        req = res.get('requests', {})
        lim = res.get('limits', {})
        print(f'{name:<30}  {req.get(\"memory\",\"—\"):<12} {lim.get(\"memory\",\"—\"):<12}  {req.get(\"cpu\",\"—\"):<12} {lim.get(\"cpu\",\"—\"):<12}')
"

echo ""

# ── Total namespace resource consumption ─────────────────────────────────────
echo "--- Namespace Totals ---"
echo ""

kubectl top pods -n "${NS}" --no-headers 2>/dev/null | \
    awk '
    BEGIN { mem_total=0; cpu_total=0; count=0 }
    {
        cpu = $2
        mem = $3
        # Strip units: cpu is in "Xm", mem is in "XMi"
        gsub(/m$/,  "", cpu)
        gsub(/Mi$/, "", mem)
        cpu_total += cpu
        mem_total += mem
        count++
    }
    END {
        printf "  Pods:       %d\n", count
        printf "  Total CPU:  %dm\n", cpu_total
        printf "  Total Mem:  %dMi (%.2f Gi)\n", mem_total, mem_total/1024
        printf "\n"
        if (mem_total > 6500) {
            printf "  ⚠  WARNING: Total memory %dMi exceeds 6500Mi safety threshold!\n", mem_total
        } else {
            printf "  ✓  Memory within budget (%dMi / 6500Mi)\n", mem_total
        }
    }
' || echo "  (metrics-server unavailable — totals not computed)"

echo ""

# ── OOMKilled detection ──────────────────────────────────────────────────────
echo "--- OOMKilled Pods ---"
echo ""
OOMKILLED=$(kubectl get pods -n "${NS}" -o json | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
found = False
for pod in data.get('items', []):
    name = pod['metadata']['name']
    for cs in pod.get('status', {}).get('containerStatuses', []):
        last = cs.get('lastState', {}).get('terminated', {})
        if last.get('reason') == 'OOMKilled':
            print(f'  ⚠  {name}: OOMKilled (exit {last.get(\"exitCode\", \"?\")})')
            found = True
if not found:
    print('  ✓  No OOMKilled pods detected')
" 2>/dev/null)
echo "${OOMKILLED}"

echo ""

# ── ResourceQuota usage ──────────────────────────────────────────────────────
echo "--- ResourceQuota ---"
echo ""
kubectl describe resourcequota -n "${NS}" 2>/dev/null || echo "  (no ResourceQuota found)"

echo ""
echo "=========================================="
echo "  Report complete"
echo "=========================================="
