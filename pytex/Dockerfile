# pytex render service (T-21): FastAPI wrapper around pytex_api.render_blob.
#
# tectonic is baked onto PATH at build time from a pinned GitHub release binary
# (static musl build, sha256-verified), so the build is deterministic and needs
# no `curl | sh` installer — the old drop-sh script failed with exit 127 in CI
# (no network to drop-sh.fullyjustified.net). No binary download happens per
# request. Only the LaTeX *bundle* is fetched lazily on the first TRUSTED build
# and persisted under $XDG_CACHE_HOME=/cache — mount the `pytex_cache` volume
# there so it survives restarts and later builds run offline
# (sds/deployment.md §1, §4).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/cache

# Pinned tectonic release (tectonic-typesetting/tectonic). To bump: update the
# version and BOTH sha256 sums from the release assets' static musl tarballs.
ARG TECTONIC_VERSION=0.15.0
ARG TECTONIC_SHA256_AMD64=dfb82876f2986862996e564fa507a9e576e0c1e3bee63c2c1bd677c2543e6407
ARG TECTONIC_SHA256_ARM64=1f59f9fb8eb65e8ba18658fc9016767e7d3e12488ded8b8fffa34254e51ce42c

# fontconfig + Basis-Fonts: ohne sie scheitert XeTeX/fontspec schon am Default-
# Font ("Fontconfig error: Cannot load default config file"). CD-spezifische
# Fonts (z. B. Blender für die STUPA-Variante) müssen zusätzlich bereitgestellt
# werden — s. /usr/share/fonts (unten optional einkopieren).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        curl ca-certificates fontconfig fonts-dejavu-core; \
    rm -rf /var/lib/apt/lists/*; \
    case "$(dpkg --print-architecture)" in \
        amd64) target="x86_64-unknown-linux-musl";  sha256="${TECTONIC_SHA256_AMD64}" ;; \
        arm64) target="aarch64-unknown-linux-musl"; sha256="${TECTONIC_SHA256_ARM64}" ;; \
        *) echo "unsupported arch: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${target}.tar.gz"; \
    curl --proto '=https' --tlsv1.2 -fsSL "$url" -o /tmp/tectonic.tar.gz; \
    echo "${sha256}  /tmp/tectonic.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic; \
    rm /tmp/tectonic.tar.gz; \
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
