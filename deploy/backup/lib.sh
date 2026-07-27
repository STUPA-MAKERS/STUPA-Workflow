#!/usr/bin/env bash
# Shared helpers for backup.sh and restore.sh (T-42, deployment.md §4).
# The code holds no secrets. Every value comes from the environment (.env or env_file).

# Read a mandatory variable. If the variable is empty, stop with a clear message.
need() {
  local name="$1" val="${!1:-}"
  if [[ -z "${val}" ]]; then
    echo "FEHLER: \$${name} nicht gesetzt (.env prüfen)." >&2
    exit 1
  fi
  printf '%s' "${val}"
}

# Build the pg_dump and pg_restore connection from POSTGRES_*. Do NOT build it from
# DATABASE_URL. That URL carries the asyncpg driver prefix (postgresql+asyncpg://…),
# which the libpq tools cannot read. The host is the compose service name.
export PGHOST="${PGHOST:-postgres}"
export PGPORT="${PGPORT:-5432}"

pg_env() {
  PGUSER="$(need POSTGRES_USER)"
  PGPASSWORD="$(need POSTGRES_PASSWORD)"
  PGDATABASE="$(need POSTGRES_DB)"
  export PGUSER PGPASSWORD PGDATABASE
}

# Set the MinIO client alias. The call is idempotent and reads MINIO_* from .env.
MC_ALIAS="${MC_ALIAS:-bk}"

mc_env() {
  local endpoint access secret scheme="http"
  endpoint="$(need MINIO_ENDPOINT)"
  access="$(need MINIO_ACCESS_KEY)"
  secret="$(need MINIO_SECRET_KEY)"
  [[ "${MINIO_SECURE:-false}" == "true" ]] && scheme="https"
  mc alias set "${MC_ALIAS}" "${scheme}://${endpoint}" "${access}" "${secret}" >/dev/null
}

# age encryption: the backup host knows only the public recipient, so it can only encrypt.
# The private identity key stays off host. Supply it at restore time only.
age_recipient() { need BACKUP_AGE_RECIPIENT; }

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }
