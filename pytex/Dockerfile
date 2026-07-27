# pytex render service (T-21): FastAPI wrapper around pytex_api.render_blob.
#
# The build installs tectonic on PATH from a pinned GitHub release binary. The
# binary is a static musl build and the build checks its sha256. The build stays
# deterministic and needs no `curl | sh` installer. The old drop-sh script
# failed with exit 127 in CI, because CI has no network route to
# drop-sh.fullyjustified.net. No request downloads a binary. Only the LaTeX
# bundle comes later. Tectonic fetches the bundle lazily on the first trusted
# build and keeps it under $XDG_CACHE_HOME=/cache. Mount the `pytex_cache`
# volume there. The cache then survives a restart and later builds run offline
# (sds/deployment.md §1, §4).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/cache

# Pinned tectonic release (tectonic-typesetting/tectonic). To bump: update the
# version and BOTH sha256 sums from the static musl tarballs of the release.
ARG TECTONIC_VERSION=0.15.0
ARG TECTONIC_SHA256_AMD64=dfb82876f2986862996e564fa507a9e576e0c1e3bee63c2c1bd677c2543e6407
ARG TECTONIC_SHA256_ARM64=1f59f9fb8eb65e8ba18658fc9016767e7d3e12488ded8b8fffa34254e51ce42c

# fontconfig plus the base fonts: without them XeTeX and fontspec fail on
# the default font ("Fontconfig error: Cannot load default config file"). Add
# the CD-specific fonts (for example Blender for the STUPA variant) on top of
# these. See /usr/share/fonts and copy them in below when you need them.
# librsvg2-bin gives rsvg-convert behind the inkscape shim (SVG logos to PDF).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        curl ca-certificates fontconfig fonts-dejavu-core librsvg2-bin; \
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

# The IncludeImage step of pytex shells out to `inkscape` to convert SVG logos
# to PDF (write_inline_logos). The shim maps that exact call onto rsvg-convert.
# The CD variants with SVG logos (for example protocol-asta: ASTA.svg) then
# render without the full Inkscape stack in the image.
COPY inkscape-shim.sh /usr/local/bin/inkscape
RUN chmod +x /usr/local/bin/inkscape

# Warm the cache at build time, where the network is available. The build
# renders one realistic document per protocol variant into /cache-seed. This
# pulls the tectonic bundle and every LaTeX package those documents need. The
# entrypoint seeds the empty /cache volume from it. The container then needs no
# internet at run time. Otherwise tectonic fetches packages per document lazily
# and dies behind an egress block ("error sending request … operation timed
# out"). The warm-up retries. It downloads the bundle, the LaTeX packages and
# the matching biber release. On a flaky build network one timeout (for example
# the biber fetch) failed the whole build. Every retry resumes from the parts
# already in the cache, so three attempts ride out short timeouts.
COPY warmup.py ./
RUN set -eux; \
    mkdir -p /cache-seed; \
    ok=0; \
    for i in 1 2 3; do \
        if XDG_CACHE_HOME=/cache-seed python warmup.py; then ok=1; break; fi; \
        echo "warmup attempt $i failed; retrying in 15s"; sleep 15; \
    done; \
    [ "$ok" = "1" ]; \
    rm -rf /tmp/pytex-api-* || true

COPY entrypoint.sh /usr/local/bin/pytex-entrypoint
RUN chmod +x /usr/local/bin/pytex-entrypoint

# The unprivileged user must read and write the cache volume and the seed,
# because the entrypoint copies the seed into the volume.
RUN useradd --create-home --uid 10001 pytex \
    && mkdir -p /cache \
    && chown -R pytex:pytex /cache /cache-seed /app
USER pytex

EXPOSE 8099

CMD ["pytex-entrypoint"]
