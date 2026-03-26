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
        build-services build-client deploy-services rollout-status \
        up up-services up-all down down-all \
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
		docker build -f services/$$svc/Dockerfile -t $$svc:$(IMAGE_TAG) . || exit 1; \
	done
	@echo "    All service images built OK"

# ─────────────────────────────────────────────────────────────────────────────
# deploy-services: apply ConfigMap, Secret, then all service manifests to k8s
# ─────────────────────────────────────────────────────────────────────────────
deploy-services:
	@echo "==> Deploying FL services to k8s..."
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
	@echo "  make build-client       — build fl-client:latest"
	@echo "  make up                 — infra only (redis, minio, postgres)"
	@echo "  make up-services        — infra + 8 FL services"
	@echo "  make up-all             — infra + services + 5 clients"
	@echo "  make down               — tear down infra"
	@echo "  make down-all           — tear down everything including clients"
	@echo "  make test-e2e           — run E2E round validation (needs make up-all)"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make deploy-services — apply ConfigMap, Secrets, and all service manifests"
	@echo "  make rollout-status  — check all deployments are ready"
	@echo ""
