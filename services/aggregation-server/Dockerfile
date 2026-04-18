# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /src

# Copy proto module (referenced by replace directive in go.mod)
COPY proto/aggregationv1/ ./proto/aggregationv1/

# Copy service source
COPY services/aggregation-server/ ./services/aggregation-server/

WORKDIR /src/services/aggregation-server
ENV GOWORK=off
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/aggregation-server ./cmd/server/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/aggregation-server /aggregation-server

EXPOSE 50051 9100

ENTRYPOINT ["/aggregation-server"]
