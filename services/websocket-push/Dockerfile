# syntax=docker/dockerfile:1
# ── WebSocket Push Service ───────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /src
COPY proto/aggregationv1/ ./proto/aggregationv1/
COPY services/websocket-push/ ./services/websocket-push/

WORKDIR /src/services/websocket-push
ENV GOWORK=off
RUN go build -o /websocket-push ./cmd/server

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /websocket-push /websocket-push

EXPOSE 8080

ENTRYPOINT ["/websocket-push"]
