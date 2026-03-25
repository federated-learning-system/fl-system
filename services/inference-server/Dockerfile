# syntax=docker/dockerfile:1
# ── Inference Server ─────────────────────────────────────────────────────────
FROM fl-base-python:latest

WORKDIR /app

# Copy shared utilities
COPY services/shared/ ./services/shared/

# Copy ML modules (tokenizer, model config)
COPY ml/model/ ./ml/model/
COPY ml/tokenizer/ ./ml/tokenizer/

# Copy inference server source
COPY services/inference-server/ ./services/inference-server/

EXPOSE 8000

CMD ["python", "services/inference-server/main.py"]
