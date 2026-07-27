#!/usr/bin/env bash
# Restore from an age-encrypted backup artifact (T-42, deployment.md section 4).
#   age -d  ->  pg_restore (DB) + mc mirror (MinIO).  DESTRUCTIVE: it overwrites the
#   running DB and the bucket. The script asks for confirmation unless FORCE=1.
#
# Usage:
#   restore.sh <artifact.tar.age>
#   FORCE=1 restore.sh <artifact.tar.age>          # no confirmation (smoke/CI)
#   BACKUP_AGE_IDENTITY=/path/key restore.sh ...   # private age key (off-host)
#
# Normal operation keeps the private age key OUT of the stack. Supply the key only at
# restore time, as a file in BACKUP_AGE_IDENTITY or as a mount.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${HERE}/lib.sh"

artifact="${1:-}"
if [[ -z "${artifact}" || ! -f "${artifact}" ]]; then
  echo "Usage: restore.sh <artefakt.tar.age>   (Datei nicht gefunden: '${artifact}')" >&2
  exit 2
fi

identity="${BACKUP_AGE_IDENTITY:-}"
if [[ -z "${identity}" || ! -f "${identity}" ]]; then
  echo "FEHLER: \$BACKUP_AGE_IDENTITY zeigt nicht auf den privaten age-Key (off-host)." >&2
  exit 1
fi

BUCKET="$(need MINIO_BUCKET)"

if [[ "${FORCE:-0}" != "1" ]]; then
  cat >&2 <<EOF
WARNUNG: Restore überschreibt die laufende Datenbank ($(need POSTGRES_DB)) und
den MinIO-Bucket (${BUCKET}) mit dem Inhalt von:
  ${artifact}
Dieser Vorgang ist NICHT umkehrbar. Vorher ein frisches Backup ziehen.
Zum Fortfahren 'RESTORE' eingeben:
EOF
  read -r confirm
  if [[ "${confirm}" != "RESTORE" ]]; then
    echo "Abgebrochen." >&2
    exit 1
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

log "Entschlüssele + entpacke ${artifact}"
age -d -i "${identity}" "${artifact}" | tar -C "${tmp}" -xf -

[[ -f "${tmp}/db.dump" ]] || { echo "FEHLER: db.dump fehlt im Artefakt." >&2; exit 1; }

# The flags --clean --if-exists drop the existing objects before the restore.
pg_env
log "pg_restore -> ${PGDATABASE}@${PGHOST}"
pg_restore --clean --if-exists --no-owner --no-privileges \
  --dbname="${PGDATABASE}" "${tmp}/db.dump"

# MinIO: --remove deletes every bucket object that the backup does not hold.
# The bucket then matches the artifact exactly.
mc_env
log "mc mirror -> ${BUCKET}"
mc mb --ignore-existing "${MC_ALIAS}/${BUCKET}" >/dev/null
mc mirror --quiet --overwrite --remove "${tmp}/objects" "${MC_ALIAS}/${BUCKET}" >/dev/null

log "Restore OK"
