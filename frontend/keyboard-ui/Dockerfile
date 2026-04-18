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

# nginx config: SPA fallback + API proxy
RUN printf 'server {\n\
  listen 3000;\n\
  root /usr/share/nginx/html;\n\
  client_max_body_size 2m;\n\
\n\
  # Proxy /api/client/ to web-bridge sidecar\n\
  location /api/client/ {\n\
    proxy_pass http://127.0.0.1:8090/;\n\
    proxy_set_header Host $host;\n\
  }\n\
\n\
  # Proxy /api/ to Inference Server\n\
  location /api/ {\n\
    proxy_pass http://inference-server:8000/;\n\
    proxy_set_header Host $host;\n\
  }\n\
\n\
  # SPA fallback\n\
  location / {\n\
    try_files $uri $uri/ /index.html;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
