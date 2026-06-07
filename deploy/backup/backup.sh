#!/usr/bin/env bash
# Tägliches verschlüsseltes Backup (T-42, deployment.md §4).
#   pg_dump (custom format) + MinIO-Spiegel (mc mirror)  ->  ein age-verschlüsseltes
#   Tar-Artefakt im backups-Volume  ->  Retention-Prune  ->  optional off-host (rsync).
# Idempotent: jeder Lauf erzeugt ein eigenes, zeitgestempeltes Artefakt; alte werden
# nach BACKUP_RETENTION_DAYS entfernt. Keine Secrets im Code (alles aus .env).
#
# Usage: backup.sh        (von entrypoint/cron oder manuell:
#                          docker compose run --rm backup backup.sh)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${HERE}/lib.sh"

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BUCKET="$(need MINIO_BUCKET)"
RECIPIENT="$(age_recipient)"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
artifact="${BACKUP_DIR}/antrag-${ts}.tar.age"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

mkdir -p "${BACKUP_DIR}"

log "Backup ${ts} -> ${artifact}"

# 1) Postgres: custom-format dump (erlaubt selektives pg_restore, Kompression).
pg_env
log "pg_dump ${PGDATABASE}@${PGHOST}"
pg_dump --format=custom --no-owner --no-privileges --file="${tmp}/db.dump"

# 2) MinIO: Bucket in lokalen Ordner spiegeln (Anhänge + PDFs).
mc_env
log "mc mirror ${BUCKET}"
mkdir -p "${tmp}/objects"
mc mirror --quiet --overwrite --remove "${MC_ALIAS}/${BUCKET}" "${tmp}/objects" >/dev/null

# 3) Tar + age-Verschlüsselung in einem Stream (kein unverschlüsseltes Tar auf Platte).
log "tar + age (recipient ${RECIPIENT})"
tar -C "${tmp}" -cf - db.dump objects | age -r "${RECIPIENT}" -o "${artifact}"
chmod 600 "${artifact}"
log "Artefakt: $(du -h "${artifact}" | cut -f1)"

# 4) Retention: ältere Artefakte entfernen.
if [[ "${RETENTION_DAYS}" -gt 0 ]]; then
  log "Prune > ${RETENTION_DAYS} Tage"
  find "${BACKUP_DIR}" -maxdepth 1 -name 'antrag-*.tar.age' -type f \
    -mtime "+${RETENTION_DAYS}" -print -delete
fi

# 5) Optional off-host: rsync-Ziel aus .env (off-host-Kopie, deployment.md §4 Risiko).
#    Schlüssel/Transport-Aufbau (SSH-Key) ist Betriebs-Sache — hier nur der Push.
if [[ -n "${BACKUP_OFFHOST_RSYNC_TARGET:-}" ]]; then
  log "off-host rsync -> ${BACKUP_OFFHOST_RSYNC_TARGET}"
  rsync -a "${artifact}" "${BACKUP_OFFHOST_RSYNC_TARGET}/"
fi

log "OK"
