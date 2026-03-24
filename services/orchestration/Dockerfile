# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /app

# Copy workspace files for module resolution
COPY go.work ./
COPY proto/aggregationv1/go.mod proto/aggregationv1/go.sum ./proto/aggregationv1/
COPY proto/aggregationv1/*.go ./proto/aggregationv1/

# Copy service source
COPY services/orchestration/go.mod services/orchestration/go.sum ./services/orchestration/
RUN cd services/orchestration && go mod download

COPY services/orchestration/ ./services/orchestration/

RUN cd services/orchestration && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/orchestration ./cmd/server/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/orchestration /orchestration

EXPOSE 8082

ENTRYPOINT ["/orchestration"]
