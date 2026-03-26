# syntax=docker/dockerfile:1
# ── FL Client Agent (simulated) ──────────────────────────────────────────────
FROM fl-base-python:latest

WORKDIR /app

# Copy shared utilities
COPY services/shared/ ./services/shared/

# Copy ML modules (model, dp_engine, tokenizer)
COPY ml/model/ ./ml/model/
COPY ml/dp_engine/ ./ml/dp_engine/
COPY ml/tokenizer/ ./ml/tokenizer/

# Copy client source (config, policy, local_trainer, agent, proto stubs)
COPY client/fl-client/ ./client/fl-client/

# Install websocket-client (not in base image)
RUN pip install --no-cache-dir websocket-client requests

# Dataset is mounted at /data via ConfigMap or volume
# Model weights are either downloaded at runtime or mounted
VOLUME ["/data", "/certs"]

ENV PYTHONUNBUFFERED=1

CMD ["python", "client/fl-client/agent.py"]
