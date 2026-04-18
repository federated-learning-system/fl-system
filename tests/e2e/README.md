# E2E Test Setup

All test endpoints are configurable via environment variables with localhost defaults.

## Docker Compose mode (defaults work as-is)

```bash
make up-all
make seed
.venv/bin/python tests/e2e/test_full_round.py
.venv/bin/python tests/e2e/test_demo_scenario.py
.venv/bin/python tests/e2e/test_straggler_demo.py
```

## k8s mode (requires port-forwards)

```bash
kubectl port-forward -n fl-system svc/redis-master 6379:6379 &
kubectl port-forward -n fl-system svc/minio 9000:9000 &
kubectl port-forward -n fl-system svc/orchestration 8082:8082 &
kubectl port-forward -n fl-system svc/client-registry 8081:8081 &
kubectl port-forward -n fl-system svc/websocket-push 8080:8080 &
kubectl port-forward -n fl-system svc/inference-server 8000:8000 &

.venv/bin/python tests/e2e/test_full_round.py
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ORCHESTRATION_URL` | `http://localhost:8082` | Orchestration controller |
| `WEBSOCKET_URL` | `ws://localhost:8080/ws` | WebSocket push service |
| `REGISTRY_URL` | `http://localhost:8081` | Client registry |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `MINIO_ENDPOINT` | `http://localhost:9000` | MinIO S3 endpoint |
| `MINIO_ACCESS_KEY` | `flminio` | MinIO access key |
| `MINIO_SECRET_KEY` | `flminio123` | MinIO secret key |
