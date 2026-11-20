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

# The build ID (§ 002150): a hash of the frontend sources, without node_modules. The same
# sources give the same ID, so a deploy that changes only the backend reloads no browser.
# The ID goes into the bundle (src/app/core/pwa/build-id.ts) and into the nginx header
# X-App-Version (/etc/nginx/app-version.conf, included by nginx.conf). The hash runs before
# the sed, because the sed changes a source file.
RUN set -eu; \
    id="$(find . -path ./node_modules -prune -o -type f -print0 | LC_ALL=C sort -z \
          | xargs -0 sha256sum | sha256sum | cut -c1-16)"; \
    sed -i "s/APP_BUILD_ID = 'dev'/APP_BUILD_ID = '${id}'/" src/app/core/pwa/build-id.ts; \
    grep -q "'${id}'" src/app/core/pwa/build-id.ts; \
    printf 'map $host $ap_app_version {\n    default "%s";\n}\n' "${id}" > /app/app-version.conf; \
    echo "build id ${id}"
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

# Bake the routing config into the image as the default. compose mounts the same file on
# top, so a production edit (real_ip CIDR) needs no rebuild.
COPY deploy/web/nginx.conf /etc/nginx/conf.d/default.conf
# The build ID of this frontend for the header X-App-Version (§ 002150).
COPY --from=build /app/app-version.conf /etc/nginx/app-version.conf

# Build output (Angular @angular/build:application -> dist/<project>/browser).
COPY --from=build /app/dist/antragsplattform/browser/ /usr/share/nginx/html/
