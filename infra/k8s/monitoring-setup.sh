#!/usr/bin/env bash
# infra/k8s/monitoring-setup.sh
# Installs kube-prometheus-stack (Prometheus + Grafana) into fl-monitoring namespace
# and imports all FLS Grafana dashboards via ConfigMaps.
# Idempotent — safe to re-run.
#
# Usage:
#   bash infra/k8s/monitoring-setup.sh           # install / upgrade all
#
# Prerequisites:
#   - k3d cluster running  (bash infra/k8s/cluster-setup.sh)
#   - fl-monitoring namespace created (cluster-setup.sh does this)
#   - helm >= 3.x
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS="fl-monitoring"

# ── Dependency checks ─────────────────────────────────────────────────────────
for cmd in helm kubectl; do
    if ! command -v "${cmd}" &>/dev/null; then
        echo "ERROR: '${cmd}' not found in PATH." >&2
        exit 1
    fi
done

# ── Ensure namespace exists ───────────────────────────────────────────────────
if ! kubectl get namespace "${NS}" &>/dev/null; then
    echo "==> Creating namespace '${NS}'..."
    kubectl create namespace "${NS}"
fi

# ── Helm repo ─────────────────────────────────────────────────────────────────
if ! helm repo list 2>/dev/null | grep -q "^prometheus-community"; then
    echo "==> Adding prometheus-community Helm repo..."
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
fi
helm repo update prometheus-community

# ── Install / upgrade kube-prometheus-stack ───────────────────────────────────
echo "==> Installing kube-prometheus-stack in '${NS}'..."
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
    --namespace "${NS}" \
    --set prometheus.prometheusSpec.serviceMonitorNamespaceSelector.matchLabels.name=fl-system \
    --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
    --set prometheus.prometheusSpec.resources.requests.memory=256Mi \
    --set prometheus.prometheusSpec.resources.limits.memory=512Mi \
    --set prometheus.prometheusSpec.resources.requests.cpu=100m \
    --set prometheus.prometheusSpec.resources.limits.cpu=500m \
    --set grafana.resources.requests.memory=128Mi \
    --set grafana.resources.limits.memory=256Mi \
    --set grafana.resources.requests.cpu=50m \
    --set grafana.resources.limits.cpu=200m \
    --set grafana.sidecar.dashboards.enabled=true \
    --set grafana.sidecar.dashboards.label=grafana_dashboard \
    --set-string grafana.sidecar.dashboards.labelValue=1 \
    --set grafana.sidecar.dashboards.searchNamespace=fl-monitoring \
    --set alertmanager.enabled=false \
    --set nodeExporter.enabled=false \
    --set kubeStateMetrics.enabled=true \
    --wait --timeout=300s

echo "    kube-prometheus-stack OK"

# ── Apply ServiceMonitors ─────────────────────────────────────────────────────
echo "==> Applying ServiceMonitors..."
kubectl apply -f "${SCRIPT_DIR}/services/service-monitors.yaml"

# ── Import Grafana dashboards via labelled ConfigMaps ─────────────────────────
# The Grafana sidecar watches for ConfigMaps with label grafana_dashboard=1
# and auto-imports them. One ConfigMap per dashboard JSON.
echo "==> Creating Grafana dashboard ConfigMaps..."
DASHBOARD_DIR="${SCRIPT_DIR}/../../monitoring/grafana"
for dashboard in "${DASHBOARD_DIR}"/*.json; do
    [[ -f "${dashboard}" ]] || continue
    name="grafana-dash-$(basename "${dashboard}" .json | tr '_' '-')"
    echo "    Importing ${name}..."
    kubectl create configmap "${name}" \
        --namespace "${NS}" \
        --from-file="$(basename "${dashboard}")=${dashboard}" \
        --dry-run=client -o yaml \
    | kubectl annotate --local -f - \
        "meta.helm.sh/release-name=monitoring" \
        "meta.helm.sh/release-namespace=${NS}" \
        --overwrite -o yaml \
    | kubectl label --local -f - grafana_dashboard=1 -o yaml \
    | kubectl apply -f -
done

echo ""
echo "==> Monitoring stack ready."
echo ""
echo "    Access Grafana:    kubectl port-forward -n ${NS} svc/monitoring-grafana 3001:80"
echo "    Access Prometheus: kubectl port-forward -n ${NS} svc/monitoring-kube-prometheus-prometheus 9090:9090"
echo "    Grafana login:     admin / prom-operator"
echo ""
echo "==> Pod status:"
kubectl get pods -n "${NS}"
