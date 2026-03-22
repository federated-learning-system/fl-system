# FLS Redis Key Schema

All FL-system state that must be shared across services in real-time lives in
Redis.  Durable state (model weights, client registry, audit log) lives in
MinIO / PostgreSQL.

Redis is deployed **without auth** in the local demo cluster.  For production,
enable `auth.enabled=true` and inject the secret via a K8s `Secret`.

---

## Namespacing convention

Keys follow the pattern `<entity>:<id>:<field>` so that `SCAN` with a prefix
glob stays efficient and namespace collisions are impossible across entities.

---

## Key catalogue

### Model metadata

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `model:current` | String | none | Version string of the globally active model (e.g. `"v3"`). Updated atomically by the aggregation-server after a successful round. |
| `model:version:{version}` | Hash | none | Metadata for a specific model version. |

**`model:version:{version}` hash fields:**

| Field | Type | Example |
|-------|------|---------|
| `version` | string | `"v3"` |
| `created_at` | unix timestamp (string) | `"1710000000"` |
| `round_id` | string | `"round-42"` |
| `num_clients` | string (int) | `"5"` |
| `accuracy` | string (float) | `"0.8712"` |
| `loss` | string (float) | `"0.4321"` |
| `onnx_s3_key` | string | `"models/v3/model.onnx"` |
| `weights_s3_key` | string | `"models/v3/weights.pt"` |

---

### FL round lifecycle

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `round:{round_id}:state` | String | 7 days | Current phase: `OPEN` → `COLLECTING` → `AGGREGATING` → `DONE` \| `FAILED` |
| `round:{round_id}:updates` | Set | 7 days | Set of `client_id` strings that have submitted a gradient update this round. |
| `round:{round_id}:config` | Hash | 7 days | Snapshot of round parameters taken when the round was opened. |

**`round:{round_id}:state` FSM:**

```
OPEN ──► COLLECTING ──► AGGREGATING ──► DONE
                                    └──► FAILED
```

- `OPEN` — round announced, clients may join
- `COLLECTING` — minimum quorum reached; no more joins accepted
- `AGGREGATING` — fedavg-engine is running FedAvg-R
- `DONE` — new global model published to MinIO; `model:current` updated
- `FAILED` — aggregation error or straggler timeout; round abandoned

**`round:{round_id}:config` hash fields:**

| Field | Example |
|-------|---------|
| `base_model_version` | `"v2"` |
| `min_clients` | `"3"` |
| `max_clients` | `"5"` |
| `deadline_unix` | `"1710003600"` |
| `dp_target_epsilon` | `"8.0"` |
| `dp_delta` | `"1e-5"` |
| `fedprox_mu` | `"0.01"` |
| `opened_at` | `"1710000000"` |

---

### Client differential-privacy budget

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `client:{client_id}:budget` | Hash | none | Running DP budget consumed by this client. Never expires — budget resets are explicit. |

**`client:{client_id}:budget` hash fields:**

| Field | Type | Description |
|-------|------|-------------|
| `dp_epsilon_cumulative` | float string | Total ε spent by this client across all rounds. |
| `dp_delta` | float string | δ used (constant; stored for audit). |
| `last_reset` | unix timestamp string | When the budget was last zeroed (e.g. at the start of a new training epoch). |
| `rounds_participated` | int string | Number of rounds this client has contributed to. |

**Budget enforcement rule** (applied in `fedavg-engine` before accepting an update):
```
if float(dp_epsilon_cumulative) + round_epsilon > MAX_EPSILON:
    reject update, return BUDGET_EXHAUSTED
```

---

### Straggler watch

| Key | Type | TTL | Description |
|-----|------|-----|-------------|
| `straggler:{round_id}:deadline` | String | auto-expires at deadline | Unix timestamp of the round deadline.  `straggler-watch` uses `EXPIREAT` so the expiry fires a `__keyevent@0__:expired` Pub/Sub event that triggers straggler detection. |

---

## Pub/Sub channels

| Channel | Publisher | Subscribers | Payload |
|---------|-----------|-------------|---------|
| `fl:round:events` | orchestration | aggregation-server, fedavg-engine, websocket-push | JSON: `{"event": "ROUND_OPENED", "round_id": "...", ...}` |
| `fl:model:updated` | aggregation-server | inference-server, websocket-push | JSON: `{"version": "v3", "onnx_s3_key": "..."}` |

---

## Seeding initial state

After Phase 2 warm-start training completes, run:

```bash
python ml/training/seed_redis.py
```

This writes `model:current` and the initial `model:version:v0` hash using the
ONNX export produced by the training pipeline.

---

## Key expiry policy

```
round:*   7d   — keep a week of round history for debugging
straggler:* auto — EXPIREAT set to the round deadline
model:*   none  — model metadata is permanent; clean up manually via admin CLI
client:*  none  — budget is permanent; reset explicitly
```

---

## Useful one-liners

```bash
# See all keys (dev only — never use KEYS in prod)
kubectl exec -n fl-system deploy/redis-master -- redis-cli KEYS '*'

# Inspect a round
kubectl exec -n fl-system deploy/redis-master -- redis-cli HGETALL round:round-1:config

# Check a client budget
kubectl exec -n fl-system deploy/redis-master -- redis-cli HGETALL client:fl-client-tech:budget

# Monitor live events
kubectl exec -n fl-system deploy/redis-master -- redis-cli SUBSCRIBE fl:round:events fl:model:updated
```
