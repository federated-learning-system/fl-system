# syntax=docker/dockerfile:1
# ── FedAvg-R Aggregation Engine ──────────────────────────────────────────────
FROM fl-base-python:latest

WORKDIR /app

# Copy shared utilities
COPY services/shared/ ./services/shared/

# Copy ML model definitions (for state_dict shape reference)
COPY ml/model/ ./ml/model/

# Copy engine source
COPY services/fedavg-engine/ ./services/fedavg-engine/

EXPOSE 9093

CMD ["python", "-m", "services.fedavg-engine.aggregator"]
