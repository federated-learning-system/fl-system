# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /app

# Copy workspace files for module resolution
COPY go.work ./
COPY proto/aggregationv1/go.mod proto/aggregationv1/go.sum ./proto/aggregationv1/
COPY proto/aggregationv1/*.go ./proto/aggregationv1/

# Copy service source
COPY services/straggler-watch/go.mod services/straggler-watch/go.sum ./services/straggler-watch/
RUN cd services/straggler-watch && go mod download

COPY services/straggler-watch/ ./services/straggler-watch/

RUN cd services/straggler-watch && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/straggler-watch ./cmd/watcher/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/straggler-watch /straggler-watch

EXPOSE 9092

ENTRYPOINT ["/straggler-watch"]
