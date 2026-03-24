# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /app

# Copy workspace files for module resolution
COPY go.work ./
COPY proto/aggregationv1/go.mod proto/aggregationv1/go.sum ./proto/aggregationv1/
COPY proto/aggregationv1/*.go ./proto/aggregationv1/

# Copy service source
COPY services/client-registry/go.mod services/client-registry/go.sum ./services/client-registry/
RUN cd services/client-registry && go mod download

COPY services/client-registry/ ./services/client-registry/

RUN cd services/client-registry && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/client-registry ./cmd/server/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/client-registry /client-registry

EXPOSE 8081

ENTRYPOINT ["/client-registry"]
