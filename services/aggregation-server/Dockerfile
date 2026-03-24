# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /app

# Copy workspace files for module resolution
COPY go.work ./
COPY proto/aggregationv1/go.mod proto/aggregationv1/go.sum ./proto/aggregationv1/
COPY proto/aggregationv1/*.go ./proto/aggregationv1/

# Copy service source
COPY services/aggregation-server/go.mod services/aggregation-server/go.sum ./services/aggregation-server/
RUN cd services/aggregation-server && go mod download

COPY services/aggregation-server/ ./services/aggregation-server/

RUN cd services/aggregation-server && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/aggregation-server ./cmd/server/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/aggregation-server /aggregation-server

EXPOSE 50051 9090

ENTRYPOINT ["/aggregation-server"]
