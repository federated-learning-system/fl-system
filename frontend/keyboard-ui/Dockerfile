# ── Build stage ────────────────────────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app

COPY frontend/keyboard-ui/package.json frontend/keyboard-ui/package-lock.json ./
RUN npm ci --ignore-scripts

COPY frontend/keyboard-ui/ ./
RUN npm run build

# ── Serve stage ───────────────────────────────────────────────────────────────
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html

# SPA fallback: route all paths to index.html
RUN printf 'server {\n\
  listen 3000;\n\
  root /usr/share/nginx/html;\n\
  location / {\n\
    try_files $uri $uri/ /index.html;\n\
  }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
