# ── Build stage ────────────────────────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app

COPY frontend/keyboard-ui/package.json frontend/keyboard-ui/package-lock.json ./
RUN npm ci --ignore-scripts

COPY frontend/keyboard-ui/ ./
# Copy WASM runtime files (onnxruntime-web WASM backend for in-browser inference)
RUN cp node_modules/onnxruntime-web/dist/*.wasm public/
RUN npm run build

# ── Serve stage ───────────────────────────────────────────────────────────────
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html

# SPA fallback + reverse proxy for backend APIs
RUN printf 'server {\n\
  listen 3000;\n\
  root /usr/share/nginx/html;\n\
\n\
  # WebSocket proxy → ws-push service\n\
  location /ws {\n\
    proxy_pass http://websocket-push:8080/ws;\n\
    proxy_http_version 1.1;\n\
    proxy_set_header Upgrade $http_upgrade;\n\
    proxy_set_header Connection "upgrade";\n\
    proxy_set_header Host $host;\n\
    proxy_read_timeout 86400;\n\
  }\n\
\n\
  # Reverse proxy: /api/rounds/ → orchestration controller\n\
  location /api/rounds/ {\n\
    proxy_pass http://orchestration:8082/rounds/;\n\
    proxy_set_header Host $host;\n\
    proxy_set_header X-Real-IP $remote_addr;\n\
  }\n\
\n\
  # Reverse proxy: /api/ → inference server\n\
  location /api/ {\n\
    proxy_pass http://inference-server:8000/;\n\
    proxy_set_header Host $host;\n\
    proxy_set_header X-Real-IP $remote_addr;\n\
  }\n\
\n\
  # SPA fallback\n\
  location / {\n\
    try_files $uri $uri/ /index.html;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
