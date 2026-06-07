# Backup-/Restore-Image (T-42): pg16-Client + MinIO-Client (mc) + age.
# Schlank auf Alpine; pg_dump/pg_restore-Version muss zur DB (postgres:16) passen.
FROM postgres:16-alpine

# bash für die Skripte, age für Verschlüsselung, rsync für optionalen off-host-Push.
# busybox-crond ist im Basis-Image (alpine) bereits vorhanden.
RUN apk add --no-cache bash age rsync curl

# MinIO-Client pinnen (reproduzierbar). Architektur über uname auflösen.
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
