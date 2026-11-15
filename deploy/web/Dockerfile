# web — multi-stage: build the Angular SPA, then let nginx serve it as static files.
# The build context is the repository root (see deploy/docker-compose.yml: context: ..),
# so both frontend/ and deploy/web/nginx.conf are in reach.
# nginx.conf holds the routing (/api proxy, WS, SPA fallback, security headers).

FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build
WORKDIR /app

# Copy the manifests first, so the npm ci layer stays cached while the deps do not change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# `npm run build` uses defaultConfiguration: production. base-href stays "/" (from
# src/index.html), so /api is same-origin.
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

# Bake the routing config into the image as the default. compose mounts the same file on
# top, so a production edit (real_ip CIDR) needs no rebuild.
COPY deploy/web/nginx.conf /etc/nginx/conf.d/default.conf

# Build output (Angular @angular/build:application -> dist/<project>/browser).
COPY --from=build /app/dist/antragsplattform/browser/ /usr/share/nginx/html/
