PROTO_SRC     := proto/aggregation_service.proto
PROTO_DIR     := proto

# Go output — shared proto module consumed by all Go services via go.work
GO_OUT        := proto/aggregationv1

# Python output dirs — only services that actually call gRPC
PY_TARGETS    := services/fedavg-engine/proto_gen \
                 services/offload-worker/proto_gen \
                 client/fl-client/proto_gen

# Always use the project venv — never the system Python
PYTHON        := .venv/bin/python3
UV            := uv

IMAGE_TAG     ?= latest
GIT_SHORT     := $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")
CLUSTER       ?= fl-demo

# All service images to build and deploy
GO_SERVICES   := aggregation-server client-registry orchestration \
                 straggler-watch websocket-push
PY_SERVICES   := fedavg-engine inference-server
HYBRID_SERVICES := offload-worker
ALL_SERVICES  := $(GO_SERVICES) $(PY_SERVICES) $(HYBRID_SERVICES)

# K8s deployment order: config/secrets first, then services by dependency
K8S_SVC_DIR   := infra/k8s/services

# Docker Compose files
COMPOSE_BASE    := docker-compose.yml
COMPOSE_CLIENTS := infra/docker-compose.clients.yml

# Client image
CLIENT_SERVICES := client-tech client-casual client-medical client-sports client-straggler

.PHONY: proto proto-go proto-python build-go test-go venv \
        build build-go-base build-python-base \
        build-services build-frontend build-client build-seed-job deploy-services deploy-monitoring rollout-status \
        import-images clean-k3d-images \
        up up-services up-all down down-all \
        up-clients-k8s down-clients-k8s port-forwards \
        seed logs logs-compose \
        export-model demo-start \
        test-e2e clean help

# ─────────────────────────────────────────────────────────────────────────────
# proto: generate stubs for Go and Python
# ─────────────────────────────────────────────────────────────────────────────
proto: proto-go proto-python

proto-go:
	@echo "==> Generating Go stubs..."
	@mkdir -p $(GO_OUT)
	protoc \
		--proto_path=$(PROTO_DIR) \
		--go_out=$(GO_OUT) \
		--go_opt=paths=source_relative \
		--go-grpc_out=$(GO_OUT) \
		--go-grpc_opt=paths=source_relative \
		$(PROTO_SRC)
	@echo "    Go stubs written to $(GO_OUT)/"
	@ls $(GO_OUT)/*.go

proto-python: venv
	@echo "==> Generating Python stubs..."
	@for dir in $(PY_TARGETS); do \
		echo "    -> $$dir"; \
		mkdir -p $$dir; \
		$(PYTHON) -m grpc_tools.protoc \
			--proto_path=$(PROTO_DIR) \
			--python_out=$$dir \
			--grpc_python_out=$$dir \
			$(PROTO_SRC); \
		touch $$dir/__init__.py; \
	done
	@echo "    Python stubs written."

GO_MODULES := proto/aggregationv1 \
              services/aggregation-server \
              services/client-registry \
              services/orchestration \
              services/straggler-watch \
              services/websocket-push

# ─────────────────────────────────────────────────────────────────────────────
# build-go: compile all Go modules (validates proto stubs compile cleanly)
# ─────────────────────────────────────────────────────────────────────────────
build-go:
	@echo "==> Building Go modules..."
	@for mod in $(GO_MODULES); do \
		echo "    Building $$mod..."; \
		(cd $$mod && go build ./...) || exit 1; \
	done
	@echo "    All Go modules build OK"

# ─────────────────────────────────────────────────────────────────────────────
# test-go: run Go unit tests across all modules
# ─────────────────────────────────────────────────────────────────────────────
test-go:
	@echo "==> Running Go tests..."
	@for mod in $(GO_MODULES); do \
		(cd $$mod && go test ./... -count=1) || exit 1; \
	done

# ─────────────────────────────────────────────────────────────────────────────
# venv: create/verify .venv using uv (idempotent)
# ─────────────────────────────────────────────────────────────────────────────
venv:
	@if [ ! -f "$(PYTHON)" ]; then \
		echo "==> Creating .venv with uv (Python 3.11)..."; \
		$(UV) venv .venv --python 3.11; \
		$(UV) pip install grpcio-tools; \
	fi

# ─────────────────────────────────────────────────────────────────────────────
# Docker image targets
# ─────────────────────────────────────────────────────────────────────────────

# build-go-base: build the shared Go builder base image
build-go-base:
	@echo "==> Building fl-base-go:$(IMAGE_TAG)..."
	docker build -f Dockerfile.base-go -t fl-base-go:$(IMAGE_TAG) .
	@echo "    fl-base-go:$(IMAGE_TAG) OK"

# build-python-base: build the shared Python ML base image
build-python-base:
	@echo "==> Building fl-base-python:$(IMAGE_TAG)..."
	docker build -f Dockerfile.base-python -t fl-base-python:$(IMAGE_TAG) .
	@echo "    fl-base-python:$(IMAGE_TAG) OK"

# build: build both base images
build: build-go-base build-python-base

# ─────────────────────────────────────────────────────────────────────────────
# build-client: build the FL client Docker image
# ─────────────────────────────────────────────────────────────────────────────
build-client: build-python-base
	@echo "==> Building fl-client:$(IMAGE_TAG)..."
	docker build -f client/fl-client/Dockerfile -t fl-client:$(IMAGE_TAG) .
	@echo "    fl-client:$(IMAGE_TAG) OK"

# ─────────────────────────────────────────────────────────────────────────────
# build-frontend: build the web frontend Docker image
# ─────────────────────────────────────────────────────────────────────────────
build-frontend:
	@echo "==> Building web-frontend:$(IMAGE_TAG)..."
	docker build -f frontend/keyboard-ui/Dockerfile -t web-frontend:$(IMAGE_TAG) .
	@echo "    web-frontend:$(IMAGE_TAG) OK"

# ─────────────────────────────────────────────────────────────────────────────
# build-seed-job: build the self-contained seed job image (model baked in)
# ─────────────────────────────────────────────────────────────────────────────
build-seed-job: build-python-base
	@echo "==> Building fl-seed-job:$(IMAGE_TAG)..."
	docker build -f infra/k8s/jobs/Dockerfile.seed -t fl-seed-job:$(IMAGE_TAG) .
	@echo "    fl-seed-job:$(IMAGE_TAG) OK"

# ─────────────────────────────────────────────────────────────────────────────
# import-images: import all service + frontend + client images into k3d
# ─────────────────────────────────────────────────────────────────────────────
import-images:
	@echo "==> Importing images into k3d cluster '$(CLUSTER)' via direct ctr import..."
	@echo "    Saving images to tarball (this may take ~30s)..."
	@docker save \
		$(addsuffix :$(IMAGE_TAG),$(ALL_SERVICES)) \
		web-frontend:$(IMAGE_TAG) \
		fl-client:$(IMAGE_TAG) \
		fl-seed-job:$(IMAGE_TAG) \
		-o /var/tmp/fls-import.tar
	@echo "    Copying and importing into k3d nodes in parallel..."
	@for node in k3d-$(CLUSTER)-server-0 k3d-$(CLUSTER)-agent-0 k3d-$(CLUSTER)-agent-1; do \
		(docker cp /var/tmp/fls-import.tar $${node}:/tmp/fls-import.tar && \
		 docker exec $${node} ctr -n k8s.io images import /tmp/fls-import.tar && \
		 docker exec $${node} rm /tmp/fls-import.tar && \
		 echo "    $${node}: done") & \
	done; wait
	@rm -f /var/tmp/fls-import.tar
	@echo "    All images imported into '$(CLUSTER)'"

# clean-k3d-images: remove stale tarballs from the k3d image volume
# Each import run leaves a tarball; accumulation causes disk pressure cascades.
clean-k3d-images:
	@echo "==> Cleaning stale k3d image tarballs from volume..."
	@docker run --rm -v k3d-fl-demo-images:/v alpine sh -c \
	  "count=\$$(ls /v/*.tar 2>/dev/null | wc -l); \
	   if [ \$$count -gt 1 ]; then \
	     ls /v/*.tar | sort | head -n -1 | xargs rm -f; \
	     echo '    Removed '\$$((\$$count - 1))' old tarball(s).'; \
	   else echo '    Nothing to clean.'; fi" 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────────────
# Docker Compose targets
# ─────────────────────────────────────────────────────────────────────────────

# up: infra only (redis, minio, postgres)
up:
	docker compose up -d

# up-services: infra + all 8 FL services
up-services:
	docker compose --profile services up -d

# up-all: infra + services + 5 simulated clients
up-all:
	docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_CLIENTS) --profile services up -d

# down: tear down infra
down:
	docker compose down

# down-all: tear down everything including clients
down-all:
	docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_CLIENTS) --profile services down

# ─────────────────────────────────────────────────────────────────────────────
# test-e2e: run end-to-end round validation (requires make up-all first)
# ─────────────────────────────────────────────────────────────────────────────
test-e2e:
	@echo "==> Running E2E round test..."
	$(PYTHON) tests/e2e/test_full_round.py

# ─────────────────────────────────────────────────────────────────────────────
# build-services: build Docker images for all 8 services
# ─────────────────────────────────────────────────────────────────────────────
build-services: build
	@echo "==> Building all service images..."
	@for svc in $(ALL_SERVICES); do \
		echo "    Building $$svc:$(IMAGE_TAG)..."; \
		docker build -f services/$$svc/Dockerfile -t $$svc:$(IMAGE_TAG) -t $$svc:$(GIT_SHORT) . || exit 1; \
	done
	@echo "    All service images built OK ($(IMAGE_TAG) + $(GIT_SHORT))"

# ─────────────────────────────────────────────────────────────────────────────
# gen-certs: generate mTLS certificate bundle (CA + server + 5 client certs)
# ─────────────────────────────────────────────────────────────────────────────
gen-certs:
	@echo "==> Generating mTLS certificates..."
	bash infra/certs/gen_certs.sh
	@echo "    Certificates generated."

# ─────────────────────────────────────────────────────────────────────────────
# seed: seed MinIO + Redis with initial model (Docker Compose mode)
# ─────────────────────────────────────────────────────────────────────────────
seed:
	@echo "==> Seeding MinIO and Redis (Docker Compose mode)..."
	REDIS_HOST=localhost \
	MINIO_ENDPOINT=http://localhost:9000 \
	MINIO_ACCESS_KEY=flminio \
	MINIO_SECRET_KEY=flminio123 \
	$(PYTHON) ml/training/seed_model_store.py
	@echo "    Seeding complete."

# ─────────────────────────────────────────────────────────────────────────────
# export-model: export LSTM → ONNX (float32 + INT8 quantized) → frontend
# ─────────────────────────────────────────────────────────────────────────────
FRONTEND_MODELS := frontend/keyboard-ui/public/models

export-model:
	@echo "==> Exporting ONNX model (float32 + INT8 quantized)..."
	$(PYTHON) ml/model/export_onnx.py
	@echo "==> Copying model + vocab to frontend..."
	cp ml/model/model_quant.onnx $(FRONTEND_MODELS)/model_quant.onnx
	cp ml/tokenizer/vocab_8192.vocab $(FRONTEND_MODELS)/vocab_8192.json
	@echo "    $(FRONTEND_MODELS)/model_quant.onnx — $$(du -h $(FRONTEND_MODELS)/model_quant.onnx | cut -f1)"
	@echo "    $(FRONTEND_MODELS)/vocab_8192.json  — $$(du -h $(FRONTEND_MODELS)/vocab_8192.json | cut -f1)"
	@echo "    Export pipeline complete."

# ─────────────────────────────────────────────────────────────────────────────
# logs: tail all FL service logs
# ─────────────────────────────────────────────────────────────────────────────
logs:
	kubectl logs -n fl-system -l app.kubernetes.io/part-of=fls --all-containers --prefix -f --max-log-requests=10

logs-compose:
	docker compose --profile services logs -f

# ─────────────────────────────────────────────────────────────────────────────
# deploy-services: apply ConfigMap, Secret, then all service manifests to k8s
# ─────────────────────────────────────────────────────────────────────────────
deploy-services:
	@echo "==> Deploying FL services to k8s..."
	@if [ ! -f infra/certs/ca.crt ]; then \
		echo "    Certificates not found, generating..."; \
		bash infra/certs/gen_certs.sh; \
	fi
	@echo "    Applying ConfigMap + Credentials..."
	kubectl apply -f $(K8S_SVC_DIR)/fl-configmap.yaml
	kubectl apply -f $(K8S_SVC_DIR)/fl-credentials-secret.yaml
	@echo "    Applying TLS secrets..."
	kubectl apply -f infra/k8s/secrets/tls-secrets.yaml
	@echo "    Deploying services..."
	@for svc in $(ALL_SERVICES); do \
		echo "    Applying $$svc..."; \
		kubectl apply -f $(K8S_SVC_DIR)/$$svc-deployment.yaml || exit 1; \
	done
	@echo "    Deploying web-frontend..."
	kubectl apply -f $(K8S_SVC_DIR)/web-frontend-deployment.yaml
	@echo "    All manifests applied"

# ─────────────────────────────────────────────────────────────────────────────
# rollout-status: check all 8 deployments are successfully rolled out
# ─────────────────────────────────────────────────────────────────────────────
rollout-status:
	@echo "==> Checking rollout status for all services..."
	@FAILED=0; \
	for svc in $(ALL_SERVICES); do \
		echo "    $$svc:"; \
		kubectl rollout status deployment/$$svc -n fl-system --timeout=120s || FAILED=1; \
	done; \
	if [ $$FAILED -eq 1 ]; then \
		echo "    [FAIL] Some deployments did not roll out"; \
		exit 1; \
	fi
	@echo "    All deployments successfully rolled out"
	@echo ""
	@echo "==> Pod status:"
	@kubectl get pods -n fl-system -l app.kubernetes.io/part-of=fls -o wide 2>/dev/null || \
		kubectl get pods -n fl-system -o wide

# ─────────────────────────────────────────────────────────────────────────────
# up-clients-k8s: start 3 FL client containers pointing at k8s cluster
# ─────────────────────────────────────────────────────────────────────────────
up-clients-k8s:
	@echo "==> Starting FL client simulators (→ k8s cluster)..."
	@echo "    Prerequisites: port-forwards for 50052, 8090, 8001, 9002 (make port-forwards)"
	docker compose -f infra/docker-compose.clients-k8s.yml up -d
	docker compose -f infra/docker-compose.clients-k8s.yml ps

down-clients-k8s:
	docker compose -f infra/docker-compose.clients-k8s.yml down

# ─────────────────────────────────────────────────────────────────────────────
# port-forwards: start all required k8s port-forwards for demo mode
# ─────────────────────────────────────────────────────────────────────────────
port-forwards:
	@echo "==> Starting port-forwards to k8s cluster..."
	@# fuser -k kills by port — safe because fuser's own cmdline never matches a port number
	@# (avoids the pkill -f self-kill bug where make's shell cmdline contains 'kubectl port-forward')
	@# Ports 8000/8080/50051 are bound by k3d serverlb (--port @loadbalancer) but its nginx has
	@# no backend for ClusterIP services — those bindings are dead. Use offset ports instead.
	@fuser -k -TERM 50052/tcp 8083/tcp 8090/tcp 8001/tcp 8091/tcp 8085/tcp 9002/tcp 9001/tcp 6379/tcp 3002/tcp 3003/tcp 2>/dev/null || true
	@sleep 1
	@# --address 0.0.0.0 is required for Docker containers to reach these via host.docker.internal
	@# Offset ports: k3d loadbalancer holds 50051, 8082, 8080, 8000, 8081, 9000, 3000 with no backend
	kubectl port-forward --address 0.0.0.0 -n fl-system svc/aggregation-server 50052:50051 &
	kubectl port-forward --address 0.0.0.0 -n fl-system svc/orchestration 8083:8082 &
	kubectl port-forward --address 0.0.0.0 -n fl-system svc/websocket-push 8090:8080 &
	kubectl port-forward --address 0.0.0.0 -n fl-system svc/inference-server 8001:8000 &
	kubectl port-forward --address 0.0.0.0 -n fl-system svc/client-registry 8091:8081 &
	kubectl port-forward --address 0.0.0.0 -n fl-system svc/offload-worker 8085:8085 &
	kubectl port-forward --address 0.0.0.0 -n fl-system svc/minio 9002:9000 &
	kubectl port-forward -n fl-system svc/minio-console 9001:9001 &
	kubectl port-forward -n fl-system svc/redis-master 6379:6379 &
	kubectl port-forward -n fl-system svc/web-frontend 3002:3000 &
	kubectl port-forward -n fl-monitoring svc/monitoring-grafana 3003:80 &
	@echo "    Port-forwards running in background."
	@echo "    aggregation-server gRPC : localhost:50052  (50051 bound by k3d)"
	@echo "    orchestration REST      : localhost:8083   (8082  bound by k3d)"
	@echo "    websocket-push          : localhost:8090   (8080  bound by k3d)"
	@echo "    inference-server        : localhost:8001   (8000  bound by k3d)"
	@echo "    client-registry         : localhost:8091   (8081  bound by k3d)"
	@echo "    offload-worker          : localhost:8085"
	@echo "    MinIO API               : localhost:9002   (9000  bound by k3d)"
	@echo "    MinIO Console           : localhost:9001"
	@echo "    Redis                   : localhost:6379"
	@echo "    Frontend                : localhost:3002   (3000  bound by k3d)"
	@echo "    Grafana                 : localhost:3003   (3001  bound by k3d)"
	@echo "    Kill all: fuser -k -TERM 50052/tcp 8083/tcp 8090/tcp 8001/tcp 8091/tcp 8085/tcp 9002/tcp 9001/tcp 6379/tcp 3002/tcp 3003/tcp"

# ─────────────────────────────────────────────────────────────────────────────
# deploy-monitoring: install kube-prometheus-stack + import Grafana dashboards
# ─────────────────────────────────────────────────────────────────────────────
deploy-monitoring:
	@echo "==> Deploying monitoring stack..."
	bash infra/k8s/monitoring-setup.sh
	@echo "    Monitoring deployed."

# ─────────────────────────────────────────────────────────────────────────────
# demo-start: full demo bootstrap (k8s mode)
# ─────────────────────────────────────────────────────────────────────────────
demo-start:
	@echo "==> FLS Demo Bootstrap"
	@echo "    Step 1: Verify k3d cluster..."
	@kubectl cluster-info &>/dev/null || { echo "ERROR: No k8s cluster. Run: bash infra/k8s/cluster-setup.sh"; exit 1; }
	@echo "    Step 2: Import images into k3d..."
	$(MAKE) import-images
	@echo "    Step 3: Deploy services..."
	$(MAKE) deploy-services
	@echo "    Step 4: Seed model (before rollout — inference-server needs seeded MinIO to start)..."
	@echo "    Starting temporary port-forwards for seeding..."
	@kubectl port-forward -n fl-system svc/redis-master 6379:6379 &>/dev/null & echo $$! > /tmp/pf_redis.pid
	@# Port 9002 — port 9000 is bound by k3d loadbalancer (--port '9000:9000@loadbalancer')
	@kubectl port-forward -n fl-system svc/minio 9002:9000 &>/dev/null & echo $$! > /tmp/pf_minio.pid
	@echo "    Waiting for port-forwards to be ready..."
	@for port in 6379 9002; do \
		for i in $$(seq 1 30); do \
			if ss -tnlp 2>/dev/null | grep -q ":$${port} " || nc -z localhost "$${port}" 2>/dev/null; then \
				echo "    Port $${port} ready."; break; \
			fi; \
			sleep 1; \
		done; \
	done
	REDIS_HOST=localhost MINIO_ENDPOINT=http://localhost:9002 \
		MINIO_ACCESS_KEY=flminio MINIO_SECRET_KEY=flminio123 \
		$(PYTHON) ml/training/seed_model_store.py
	REDIS_HOST=localhost $(PYTHON) ml/training/seed_redis.py
	@kill $$(cat /tmp/pf_redis.pid /tmp/pf_minio.pid 2>/dev/null) 2>/dev/null || true
	@rm -f /tmp/pf_redis.pid /tmp/pf_minio.pid
	@echo "    Restarting inference-server to pick up seeded model..."
	@kubectl rollout restart deployment/inference-server -n fl-system
	@echo "    Step 5: Wait for rollout..."
	$(MAKE) rollout-status
	@echo "    Step 6: Start port-forwards..."
	$(MAKE) port-forwards
	@echo ""
	@echo "==> Demo ready!"
	@echo "    Frontend:       http://localhost:3002"
	@echo "    MinIO Console:  http://localhost:9001"
	@echo "    Grafana:        http://localhost:3003  (admin / prom-operator)"
	@echo "    Orchestration:  http://localhost:8083/rounds/start  (POST to trigger round)"
	@echo "    Clients:        make up-clients-k8s"

# ─────────────────────────────────────────────────────────────────────────────
# clean: remove generated stubs
# ─────────────────────────────────────────────────────────────────────────────
clean:
	@echo "==> Cleaning generated stubs..."
	rm -f $(GO_OUT)/*.go
	@for dir in $(PY_TARGETS); do \
		rm -f $$dir/*_pb2.py $$dir/*_pb2_grpc.py; \
	done
	@echo "    Done."

# ─────────────────────────────────────────────────────────────────────────────
# help
# ─────────────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  make venv           — create .venv via uv (auto-called by proto-python)"
	@echo "  make proto          — generate Go + Python stubs from proto/"
	@echo "  make proto-go       — Go stubs only"
	@echo "  make proto-python   — Python stubs only (creates venv if missing)"
	@echo "  make build-go       — compile all Go modules (needs: make proto first)"
	@echo "  make test-go        — run all Go tests"
	@echo "  make clean          — delete generated stub files"
	@echo ""
	@echo "Docker:"
	@echo "  make build              — build both base Docker images"
	@echo "  make build-go-base      — build fl-base-go:latest"
	@echo "  make build-python-base  — build fl-base-python:latest"
	@echo "  make build-services     — build all 8 service Docker images"
	@echo "  make build-frontend     — build web-frontend Docker image"
	@echo "  make build-client       — build fl-client:latest"
	@echo "  make build-seed-job     — build fl-seed-job:latest (model baked in)"
	@echo "  make import-images      — import all images into k3d (CLUSTER=fl-demo)"
	@echo "  make up                 — infra only (redis, minio, postgres)"
	@echo "  make up-services        — infra + 8 FL services"
	@echo "  make up-all             — infra + services + 5 clients"
	@echo "  make down               — tear down infra"
	@echo "  make down-all           — tear down everything including clients"
	@echo "  make seed               — seed MinIO + Redis with initial model (Compose mode)"
	@echo "  make export-model       — export LSTM to ONNX + INT8, copy to frontend/public/models/"
	@echo "  make logs               — tail all service logs (k8s mode)"
	@echo "  make logs-compose       — tail all service logs (Docker Compose mode)"
	@echo "  make test-e2e           — run E2E round validation (needs make up-all)"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make import-images      — import all images into k3d cluster (run before deploy)"
	@echo "  make deploy-services    — apply ConfigMap, Secrets, and all service manifests (incl. frontend)"
	@echo "  make deploy-monitoring  — install kube-prometheus-stack + import Grafana dashboards"
	@echo "  make rollout-status     — check all deployments are ready"
	@echo "  make port-forwards      — start port-forwards for all k8s services (demo mode)"
	@echo "  make up-clients-k8s     — start 3 FL clients connecting to k8s cluster"
	@echo "  make down-clients-k8s   — stop k8s-mode FL clients"
	@echo "  make demo-start         — full demo bootstrap: import → deploy → rollout → port-forwards → seed"
	@echo ""
