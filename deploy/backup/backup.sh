#!/usr/bin/env bash
# Daily encrypted backup (T-42, deployment.md §4).
# The script dumps Postgres in custom format and mirrors the MinIO bucket. It writes both
# into one age-encrypted tar artifact in the backups volume. It then prunes old artifacts.
# When a target is set, it pushes the new artifact off host with rsync.
# Each run writes its own artifact with a UTC timestamp, so the script is idempotent.
# The script deletes artifacts older than BACKUP_RETENTION_DAYS. It holds no secrets and
# reads every value from .env.
# Usage: backup.sh        (from the entrypoint or cron, or by hand:
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

# 1) Postgres: dump in custom format. That allows a selective pg_restore and compression.
pg_env
log "pg_dump ${PGDATABASE}@${PGHOST}"
pg_dump --format=custom --no-owner --no-privileges --file="${tmp}/db.dump"

# 2) MinIO: mirror the bucket into a local folder. It holds the attachments and the PDFs.
mc_env
log "mc mirror ${BUCKET}"
mkdir -p "${tmp}/objects"
mc mirror --quiet --overwrite --remove "${MC_ALIAS}/${BUCKET}" "${tmp}/objects" >/dev/null

# 3) Tar and age encryption in one stream. No unencrypted tar reaches the disk.
log "tar + age (recipient ${RECIPIENT})"
tar -C "${tmp}" -cf - db.dump objects | age -r "${RECIPIENT}" -o "${artifact}"
chmod 600 "${artifact}"
log "Artefakt: $(du -h "${artifact}" | cut -f1)"

if [[ "${RETENTION_DAYS}" -gt 0 ]]; then
  log "Prune > ${RETENTION_DAYS} Tage"
  find "${BACKUP_DIR}" -maxdepth 1 -name 'antrag-*.tar.age' -type f \
    -mtime "+${RETENTION_DAYS}" -print -delete
fi

# 4) Optional off-host copy to the rsync target from .env (deployment.md §4 risk).
#    Operations must set up the SSH key and the transport. This script only pushes.
if [[ -n "${BACKUP_OFFHOST_RSYNC_TARGET:-}" ]]; then
  log "off-host rsync -> ${BACKUP_OFFHOST_RSYNC_TARGET}"
  rsync -a "${artifact}" "${BACKUP_OFFHOST_RSYNC_TARGET}/"
fi

log "OK"
