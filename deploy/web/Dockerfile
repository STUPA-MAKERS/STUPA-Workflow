# web — Multi-Stage: Angular-SPA bauen, dann von nginx statisch ausliefern.
# Build-Context = Repo-Root (siehe deploy/docker-compose.yml: context: ..),
# damit sowohl frontend/ als auch deploy/web/nginx.conf erreichbar sind.
# Routing (/api-Proxy, WS, SPA-Fallback, Security-Header) in nginx.conf.

# ---- Stage 1: Build -------------------------------------------------------- #
FROM node:22-alpine AS build
WORKDIR /app

# Erst nur Manifeste -> npm-ci-Layer cachen, solange deps unverändert.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Restliche Quellen + Produktionsbuild (defaultConfiguration: production).
# base-href bleibt "/" (aus src/index.html), same-origin /api.
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Serve -------------------------------------------------------- #
FROM nginx:1.27-alpine

# Routing-Config ins Image backen (Default). In compose wird dieselbe Datei
# zusätzlich gemountet, damit prod-spezifische Edits (real_ip-CIDR) ohne
# Rebuild möglich bleiben.
COPY deploy/web/nginx.conf /etc/nginx/conf.d/default.conf

# Build-Output (Angular @angular/build:application -> dist/<proj>/browser).
COPY --from=build /app/dist/antragsplattform/browser/ /usr/share/nginx/html/
