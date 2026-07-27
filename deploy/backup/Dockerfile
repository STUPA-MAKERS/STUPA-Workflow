# Backup and restore image (T-42): pg16 client, MinIO client (mc) and age.
# The pg_dump and pg_restore version must match the database (postgres:16).
FROM postgres:16-alpine

# bash runs the scripts, age encrypts the artifact, and rsync serves the off-host push.
# The alpine base image already contains busybox crond.
RUN apk add --no-cache bash age rsync curl

# Pin the MinIO client so that the build stays reproducible.
ARG MC_VERSION=RELEASE.2025-04-16T18-13-26Z
RUN set -eux; \
    case "$(uname -m)" in \
      x86_64)  arch=amd64 ;; \
      aarch64) arch=arm64 ;; \
      *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://dl.min.io/client/mc/release/linux-${arch}/archive/mc.${MC_VERSION}" \
      -o /usr/local/bin/mc; \
    chmod +x /usr/local/bin/mc; \
    mc --version

COPY *.sh /opt/backup/
RUN chmod +x /opt/backup/*.sh
ENV PATH="/opt/backup:${PATH}"

ENTRYPOINT ["/opt/backup/entrypoint.sh"]
