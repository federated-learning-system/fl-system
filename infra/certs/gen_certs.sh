#!/usr/bin/env bash
# infra/certs/gen_certs.sh
# Generates a local CA, server cert (mTLS), and 5 per-client certs for the
# FLS federated learning demo.  All output lands in the same directory as this
# script so it can be run from anywhere.
#
# Usage:
#   bash infra/certs/gen_certs.sh          # generate everything
#   bash infra/certs/gen_certs.sh --clean  # remove all generated files first
#
# Requirements: openssl >= 3.x (ships on Arch, Debian 12+, macOS 13+)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${SCRIPT_DIR}"
K8S_SECRETS="${SCRIPT_DIR}/../../infra/k8s/secrets/tls-secrets.yaml"

# Normalise the k8s path (resolve symlinks / ..)
K8S_SECRETS="$(cd "$(dirname "${K8S_SECRETS}")" && pwd)/$(basename "${K8S_SECRETS}")"

# ── Clean flag ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--clean" ]]; then
    echo "==> Cleaning generated cert files..."
    rm -f "${OUT}"/{ca,server,client-*}.{crt,key,csr} \
          "${OUT}"/{ca,server,client-*}-ext.cnf \
          "${K8S_SECRETS}"
    echo "    Done."
    exit 0
fi

# ── Configuration ─────────────────────────────────────────────────────────────
CA_DAYS=3650        # 10-year root CA for demo
CERT_DAYS=825       # server / client certs — matches browser max (conservative)
KEY_BITS=4096       # RSA key size for CA
LEAF_KEY_BITS=2048  # RSA key size for leaf certs (faster, still secure)
CA_SUBJ="/C=FI/ST=Demo/L=Demo/O=FLS-Demo/OU=CA/CN=FLS-Root-CA"
SERVER_SUBJ="/C=FI/ST=Demo/L=Demo/O=FLS-Demo/OU=Server/CN=aggregation-server"
# Clients get different CNs so the server can distinguish them
CLIENTS=(tech casual medical sports mixed)

echo "==> Generating FLS mTLS certificate bundle in ${OUT}/"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Root CA
# ─────────────────────────────────────────────────────────────────────────────
echo "--> [1/3] Root CA"
openssl genrsa -out "${OUT}/ca.key" ${KEY_BITS} 2>/dev/null
openssl req -new -x509 \
    -key  "${OUT}/ca.key" \
    -out  "${OUT}/ca.crt" \
    -days ${CA_DAYS} \
    -subj "${CA_SUBJ}" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:1" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash"
echo "    ca.key / ca.crt  OK"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Server cert — signed by CA, includes SANs for local demo
# ─────────────────────────────────────────────────────────────────────────────
echo "--> [2/3] Server cert (aggregation-server)"

# SAN extension config — covers localhost, service DNS name, and local subnet
cat > "${OUT}/server-ext.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions     = v3_req
prompt             = no

[req_distinguished_name]
C  = FI
ST = Demo
L  = Demo
O  = FLS-Demo
OU = Server
CN = aggregation-server

[v3_req]
basicConstraints = CA:FALSE
keyUsage         = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName   = @alt_names

[alt_names]
DNS.1 = aggregation-server
DNS.2 = localhost
DNS.3 = aggregation-server.fl-net
IP.1  = 127.0.0.1
IP.2  = 192.168.1.1
IP.3  = 192.168.1.2
IP.4  = 192.168.1.3
IP.5  = 192.168.1.4
IP.6  = 192.168.1.5
EOF

openssl genrsa -out "${OUT}/server.key" ${LEAF_KEY_BITS} 2>/dev/null
openssl req -new \
    -key  "${OUT}/server.key" \
    -out  "${OUT}/server.csr" \
    -subj "${SERVER_SUBJ}" \
    -config "${OUT}/server-ext.cnf"
openssl x509 -req \
    -in   "${OUT}/server.csr" \
    -CA   "${OUT}/ca.crt" \
    -CAkey "${OUT}/ca.key" \
    -CAcreateserial \
    -out  "${OUT}/server.crt" \
    -days ${CERT_DAYS} \
    -extensions v3_req \
    -extfile "${OUT}/server-ext.cnf" 2>/dev/null
echo "    server.key / server.crt  OK"

# ─────────────────────────────────────────────────────────────────────────────
# 3. Per-client certs — one per simulated FL client profile
# ─────────────────────────────────────────────────────────────────────────────
echo "--> [3/3] Client certs (${CLIENTS[*]})"

# Client extension config — same template for all clients; CN varies
cat > "${OUT}/client-ext.cnf" <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions     = v3_req
prompt             = no

[req_distinguished_name]
C  = FI
ST = Demo
L  = Demo
O  = FLS-Demo
OU = Client
CN = PLACEHOLDER

[v3_req]
basicConstraints = CA:FALSE
keyUsage         = critical, digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EOF

for client in "${CLIENTS[@]}"; do
    # Patch CN in a temp copy so we don't leave per-client cnf files
    TMP_CNF="${OUT}/client-${client}-ext.cnf"
    sed "s/CN = PLACEHOLDER/CN = fl-client-${client}/" \
        "${OUT}/client-ext.cnf" > "${TMP_CNF}"

    openssl genrsa -out "${OUT}/client-${client}.key" ${LEAF_KEY_BITS} 2>/dev/null
    openssl req -new \
        -key  "${OUT}/client-${client}.key" \
        -out  "${OUT}/client-${client}.csr" \
        -subj "/C=FI/ST=Demo/L=Demo/O=FLS-Demo/OU=Client/CN=fl-client-${client}" \
        -config "${TMP_CNF}"
    openssl x509 -req \
        -in    "${OUT}/client-${client}.csr" \
        -CA    "${OUT}/ca.crt" \
        -CAkey "${OUT}/ca.key" \
        -CAcreateserial \
        -out   "${OUT}/client-${client}.crt" \
        -days  ${CERT_DAYS} \
        -extensions v3_req \
        -extfile "${TMP_CNF}" 2>/dev/null
    rm -f "${TMP_CNF}" "${OUT}/client-${client}.csr"
    echo "    client-${client}.key / client-${client}.crt  OK"
done

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup intermediates
# ─────────────────────────────────────────────────────────────────────────────
rm -f "${OUT}/server.csr" "${OUT}/server-ext.cnf" "${OUT}/client-ext.cnf" "${OUT}/*.srl"

# ─────────────────────────────────────────────────────────────────────────────
# 4. Verify the chain for server + every client cert
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "--> Verifying certificate chain..."
VERIFY_OK=true
for cert in "${OUT}/server.crt" "${OUT}"/client-*.crt; do
    result=$(openssl verify -CAfile "${OUT}/ca.crt" "${cert}" 2>&1)
    if echo "${result}" | grep -q ": OK"; then
        echo "    ${result}"
    else
        echo "    FAIL: ${result}"
        VERIFY_OK=false
    fi
done

if [[ "${VERIFY_OK}" != "true" ]]; then
    echo "ERROR: chain verification failed" >&2
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. Generate K8s Secret manifest (base64-encoded, not committed to git)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "--> Writing K8s TLS Secret manifest to ${K8S_SECRETS}"

b64() { base64 -w0 < "$1"; }

cat > "${K8S_SECRETS}" <<YAML
# AUTO-GENERATED by infra/certs/gen_certs.sh — DO NOT COMMIT
# Apply with: kubectl apply -f infra/k8s/secrets/tls-secrets.yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: fls-ca
  namespace: fl-system
type: Opaque
data:
  ca.crt: $(b64 "${OUT}/ca.crt")
---
apiVersion: v1
kind: Secret
metadata:
  name: fls-server-tls
  namespace: fl-system
type: kubernetes.io/tls
data:
  tls.crt: $(b64 "${OUT}/server.crt")
  tls.key: $(b64 "${OUT}/server.key")
YAML

# Append one Secret per client
for client in "${CLIENTS[@]}"; do
cat >> "${K8S_SECRETS}" <<YAML
---
apiVersion: v1
kind: Secret
metadata:
  name: fls-client-${client}-tls
  namespace: fl-system
type: kubernetes.io/tls
data:
  tls.crt: $(b64 "${OUT}/client-${client}.crt")
  tls.key: $(b64 "${OUT}/client-${client}.key")
YAML
done

echo "    tls-secrets.yaml  OK"

# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "==> Certificate bundle complete."
echo ""
echo "    Files in ${OUT}/:"
ls -1 "${OUT}"/*.{crt,key} 2>/dev/null | sed 's/^/      /'
echo ""
echo "    Quick checks:"
echo "      openssl verify -CAfile infra/certs/ca.crt infra/certs/server.crt"
echo "      openssl verify -CAfile infra/certs/ca.crt infra/certs/client-tech.crt"
echo "      openssl x509 -noout -text -in infra/certs/server.crt | grep -A4 'Subject Alternative'"
