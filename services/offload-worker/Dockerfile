# syntax=docker/dockerfile:1
# ── Offload Worker: Go API + Python Trainer in one pod ───────────────────────

# ── Stage 1: Build Go API ────────────────────────────────────────────────────
FROM fl-base-go:latest AS go-builder

WORKDIR /src
COPY proto/aggregationv1/ ./proto/aggregationv1/
COPY services/offload-worker/api/ ./services/offload-worker/api/

WORKDIR /src/services/offload-worker/api
ENV GOWORK=off
RUN go build -o /offload-api ./cmd/api

# ── Stage 2: Final image (Python base + Go binary) ──────────────────────────
FROM fl-base-python:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Go binary
COPY --from=go-builder /offload-api /usr/local/bin/offload-api

# Copy shared utilities
COPY services/shared/ ./services/shared/

# Copy ML modules (model definition, DP engine, tokenizer)
COPY ml/model/ ./ml/model/
COPY ml/dp_engine/ ./ml/dp_engine/
COPY ml/tokenizer/ ./ml/tokenizer/

# Copy trainer source
COPY services/offload-worker/ ./services/offload-worker/

# Supervisord config
COPY services/offload-worker/supervisord.conf /etc/supervisor/conf.d/offload.conf

EXPOSE 8085

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/offload.conf"]
