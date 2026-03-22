# FLS mTLS Certificate Bundle

All services in FLS communicate over mutual TLS (mTLS).  This directory
contains the generation script and **gitignored** certificate files.

## Quick start

```bash
# From the repo root:
bash infra/certs/gen_certs.sh
```

Generates:

| File | Description |
|------|-------------|
| `ca.crt` / `ca.key` | Self-signed root CA (10-year, demo only) |
| `server.crt` / `server.key` | aggregation-server leaf cert; SANs: `localhost`, `aggregation-server`, `aggregation-server.fl-net`, `127.0.0.1`, `192.168.1.1–5` |
| `client-{tech,casual,medical,sports,mixed}.crt/key` | Per-client leaf certs, `extendedKeyUsage=clientAuth` |
| `infra/k8s/secrets/tls-secrets.yaml` | K8s `Secret` manifests (base64-encoded, not committed) |

## Regenerating certs

```bash
bash infra/certs/gen_certs.sh --clean   # removes all generated files
bash infra/certs/gen_certs.sh           # regenerates everything
```

## Loading into Kubernetes

```bash
# Create the namespace first if it doesn't exist
kubectl create namespace fl-system --dry-run=client -o yaml | kubectl apply -f -

# Apply all TLS secrets at once
kubectl apply -f infra/k8s/secrets/tls-secrets.yaml

# Verify
kubectl get secrets -n fl-system
```

## Adding a new client cert

Edit `gen_certs.sh` and add the new name to the `CLIENTS` array, then re-run
the script.  The K8s manifest will be regenerated automatically.

## Verifying the chain manually

```bash
# Server cert chain
openssl verify -CAfile infra/certs/ca.crt infra/certs/server.crt

# Client cert chain
openssl verify -CAfile infra/certs/ca.crt infra/certs/client-tech.crt

# Inspect SANs
openssl x509 -noout -text -in infra/certs/server.crt \
  | grep -A6 "Subject Alternative Name"

# Live mTLS handshake test (two terminals)
# Terminal 1 — server:
openssl s_server \
  -cert infra/certs/server.crt -key infra/certs/server.key \
  -CAfile infra/certs/ca.crt -Verify 1 -port 4433

# Terminal 2 — client:
openssl s_client \
  -cert infra/certs/client-tech.crt -key infra/certs/client-tech.key \
  -CAfile infra/certs/ca.crt -connect localhost:4433
# Expected: "Verify return code: 0 (ok)"
```

## Security notes

- **Never commit** `*.key`, `*.crt`, `*.csr`, or `tls-secrets.yaml` — the
  `.gitignore` blocks them.
- The root CA key (`ca.key`) is kept on disk for convenience during local
  development only.  For production, store it in a HSM or Vault.
- Leaf certs are valid for 825 days (conservative browser-safe maximum).
- Key size: CA=4096-bit RSA, leaves=2048-bit RSA.
