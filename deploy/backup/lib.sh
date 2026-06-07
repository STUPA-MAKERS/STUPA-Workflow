#!/usr/bin/env bash
# Gemeinsame Helfer für backup.sh / restore.sh (T-42, deployment.md §4).
# Keine Secrets im Code — alles aus der Umgebung (.env / env_file).

# Pflichtvariable lesen oder mit klarer Meldung abbrechen.
need() {
  local name="$1" val="${!1:-}"
  if [[ -z "${val}" ]]; then
    echo "FEHLER: \$${name} nicht gesetzt (.env prüfen)." >&2
    exit 1
  fi
  printf '%s' "${val}"
}

# pg_dump/pg_restore-Verbindung aus POSTGRES_* ableiten. Bewusst NICHT aus
# DATABASE_URL: die trägt den asyncpg-Treiber (postgresql+asyncpg://…), den die
# libpq-Tools nicht verstehen. Host ist der compose-Servicename.
export PGHOST="${PGHOST:-postgres}"
export PGPORT="${PGPORT:-5432}"

pg_env() {
  PGUSER="$(need POSTGRES_USER)"
  PGPASSWORD="$(need POSTGRES_PASSWORD)"
  PGDATABASE="$(need POSTGRES_DB)"
  export PGUSER PGPASSWORD PGDATABASE
}

# MinIO-Client-Alias setzen (idempotent). Liest MINIO_* aus .env.
MC_ALIAS="${MC_ALIAS:-bk}"

mc_env() {
  local endpoint access secret scheme="http"
  endpoint="$(need MINIO_ENDPOINT)"
  access="$(need MINIO_ACCESS_KEY)"
  secret="$(need MINIO_SECRET_KEY)"
  [[ "${MINIO_SECURE:-false}" == "true" ]] && scheme="https"
  mc alias set "${MC_ALIAS}" "${scheme}://${endpoint}" "${access}" "${secret}" >/dev/null
}

# age-Verschlüsselung: Backup-Host kennt nur den PUBLIC recipient (encrypt-only).
# Der private identity-Key liegt off-host und wird erst zur Restore-Zeit gestellt.
age_recipient() { need BACKUP_AGE_RECIPIENT; }

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
