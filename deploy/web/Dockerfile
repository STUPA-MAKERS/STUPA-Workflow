# web — multi-stage: build the Angular SPA, then let nginx serve it as static files.
# The build context is the repository root (see deploy/docker-compose.yml: context: ..),
# so both frontend/ and deploy/web/nginx.conf are in reach.
# nginx.conf holds the routing (/api proxy, WS, SPA fallback, security headers).

FROM node:22-alpine AS build
WORKDIR /app

# Copy the manifests first, so the npm ci layer stays cached while the deps do not change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# `npm run build` uses defaultConfiguration: production. base-href stays "/" (from
# src/index.html), so /api is same-origin.
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine

# Bake the routing config into the image as the default. compose mounts the same file on
# top, so a production edit (real_ip CIDR) needs no rebuild.
COPY deploy/web/nginx.conf /etc/nginx/conf.d/default.conf

# Build output (Angular @angular/build:application -> dist/<project>/browser).
COPY --from=build /app/dist/antragsplattform/browser/ /usr/share/nginx/html/
