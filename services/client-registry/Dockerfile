# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /src

# Copy proto module (referenced by replace directive in go.mod)
COPY proto/aggregationv1/ ./proto/aggregationv1/

# Copy service source
COPY services/client-registry/ ./services/client-registry/

WORKDIR /src/services/client-registry
ENV GOWORK=off
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/client-registry ./cmd/server/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/client-registry /client-registry

EXPOSE 8081

ENTRYPOINT ["/client-registry"]
