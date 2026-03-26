# syntax=docker/dockerfile:1
# ── Build stage ──────────────────────────────────────────────────────────────
FROM fl-base-go:latest AS builder

WORKDIR /src

# Copy proto module (referenced by replace directive in go.mod)
COPY proto/aggregationv1/ ./proto/aggregationv1/

# Copy service source
COPY services/orchestration/ ./services/orchestration/

WORKDIR /src/services/orchestration
ENV GOWORK=off
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /bin/orchestration ./cmd/server/

# ── Final stage ──────────────────────────────────────────────────────────────
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /bin/orchestration /orchestration

EXPOSE 8082

ENTRYPOINT ["/orchestration"]
