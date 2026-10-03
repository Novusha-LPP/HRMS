# The web app: built once per release, then promoted unchanged from testing to production.
# Per-environment settings come from the container's environment at start (40-hrms-config.sh).
# Build from the repository root:  docker build -f deploy/web/Dockerfile .
FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY deploy/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/web/40-hrms-config.sh /docker-entrypoint.d/40-hrms-config.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
