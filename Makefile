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

.PHONY: proto proto-go proto-python build-go test-go venv \
        build build-go-base build-python-base \
        up down clean help

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

# up / down: manage the compose stack (infra only by default)
up:
	docker compose up -d

down:
	docker compose down

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
	@echo "  make build          — build both base Docker images"
	@echo "  make build-go-base  — build fl-base-go:latest"
	@echo "  make build-python-base — build fl-base-python:latest"
	@echo "  make up             — docker compose up -d (infra)"
	@echo "  make down           — docker compose down"
	@echo ""
