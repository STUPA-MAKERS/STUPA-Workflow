#!/usr/bin/env bash
# Restore aus einem age-verschlüsselten Backup-Artefakt (T-42, deployment.md §4).
#   age -d  ->  pg_restore (DB) + mc mirror (MinIO).  ZERSTÖRERISCH: überschreibt
#   die laufende DB und den Bucket. Daher Pflicht-Bestätigung, sofern nicht FORCE=1.
#
# Usage:
#   restore.sh <artefakt.tar.age>
#   FORCE=1 restore.sh <artefakt.tar.age>          # ohne Rückfrage (Smoke/CI)
#   BACKUP_AGE_IDENTITY=/pfad/key restore.sh ...    # privater age-Key (off-host)
#
# Der private age-Key liegt im Normalbetrieb NICHT im Stack — er wird nur zur
# Restore-Zeit gestellt (Datei via BACKUP_AGE_IDENTITY oder gemountet).
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

# --- Sicherheitsabfrage: Restore ist destruktiv (DB + Bucket werden ersetzt). ---
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

# 1) Postgres: --clean --if-exists droppt vorhandene Objekte vor dem Wiederherstellen.
pg_env
log "pg_restore -> ${PGDATABASE}@${PGHOST}"
pg_restore --clean --if-exists --no-owner --no-privileges \
  --dbname="${PGDATABASE}" "${tmp}/db.dump"

# 2) MinIO: Spiegel zurückschreiben. --remove entfernt im Bucket, was im Backup
#    fehlt -> exakter Stand des Artefakts.
mc_env
log "mc mirror -> ${BUCKET}"
mc mb --ignore-existing "${MC_ALIAS}/${BUCKET}" >/dev/null
mc mirror --quiet --overwrite --remove "${tmp}/objects" "${MC_ALIAS}/${BUCKET}" >/dev/null

log "Restore OK"
