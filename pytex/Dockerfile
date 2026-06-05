# pytex render service (T-21): FastAPI wrapper around pytex_api.render_blob.
#
# tectonic is baked onto PATH at build time via the official static-binary
# installer (the same drop-sh script pytex itself would fetch at runtime), so no
# binary download happens per request. Only the LaTeX *bundle* is fetched lazily
# on the first TRUSTED build and persisted under $XDG_CACHE_HOME=/cache — mount
# the `pytex_cache` volume there so it survives restarts and later builds run
# offline (sds/deployment.md §1, §4).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/cache

# tectonic version to install; the drop-sh script honours TECTONIC_VERSION so the
# binary is pinned for a reproducible image (pytex itself is pinned via pip).
ARG TECTONIC_VERSION=0.15.0

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    cd /usr/local/bin; \
    TECTONIC_VERSION="${TECTONIC_VERSION}" \
        sh -c "curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh"; \
    chmod +x /usr/local/bin/tectonic; \
    tectonic --version

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py ./

# Drop privileges; the cache volume must be writable by the unprivileged user.
RUN useradd --create-home --uid 10001 pytex \
    && mkdir -p /cache \
    && chown -R pytex:pytex /cache /app
USER pytex

EXPOSE 8099

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8099"]
