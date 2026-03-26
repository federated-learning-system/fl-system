# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /src

# Copy proto module (referenced by replace directive in go.mod)
COPY proto/aggregationv1/ ./proto/aggregationv1/

# Copy service source
COPY services/straggler-watch/ ./services/straggler-watch/

WORKDIR /src/services/straggler-watch
ENV GOWORK=off
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/straggler-watch ./cmd/watcher/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/straggler-watch /straggler-watch

EXPOSE 9092

ENTRYPOINT ["/straggler-watch"]
