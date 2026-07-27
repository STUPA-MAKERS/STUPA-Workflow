#!/usr/bin/env bash
# Restore smoke test (T-42 AK). The script proves the backup and restore round trip in a
# throwaway stack:
#   start postgres + minio -> seed test data -> backup.sh -> destroy the data ->
#   restore.sh -> check that the DB row AND the MinIO object come back.
# The script creates an EPHEMERAL age key file inside the throwaway stack and deletes it
# again. It removes the whole stack at the end (down -v). Each run starts fresh, so the
# script is idempotent.
#
# Usage: scripts/restore-smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="${ROOT}/deploy"
SECRETS="${DEPLOY}/backup/secrets"
KEY="${SECRETS}/age.key"
MARKER="restore-smoke-$(date -u +%s)"

cd "${DEPLOY}"

# The script uses its own compose project, so it does not touch a real stack.
export COMPOSE_PROJECT_NAME="antrag-restore-smoke"
DC=(docker compose --profile backup)

# The backup service definition has `env_file: .env`, so deploy/.env must exist. Compose
# needs the file for the substitution AND for the container environment. The script moves
# a real .env aside and puts it back at the end, so the smoke test overwrites nothing.
ENV_BAK=""
cleanup() {
  "${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "${KEY}"
  rm -f "${DEPLOY}/.env"
  [[ -n "${ENV_BAK}" ]] && mv "${ENV_BAK}" "${DEPLOY}/.env"
}
trap cleanup EXIT

echo "==> .env vorbereiten"
if [[ -f "${DEPLOY}/.env" ]]; then
  ENV_BAK="${DEPLOY}/.env.restore-smoke.bak"
  mv "${DEPLOY}/.env" "${ENV_BAK}"
fi
cp .env.example .env
# Replace the .env.example placeholders with values that work for the smoke test.
{
  echo "POSTGRES_PASSWORD=smokepw"
  echo "MINIO_ACCESS_KEY=smokeaccess"
  echo "MINIO_SECRET_KEY=smokesecret123"
} >> .env

echo "==> backup-Image bauen"
"${DC[@]}" build backup >/dev/null

echo "==> ephemeres age-Schlüsselpaar erzeugen"
mkdir -p "${SECRETS}"
# age-keygen lives in the backup image. Write the key pair to STDOUT and store it on the
# HOST, because the container mounts /secrets read-only. The output holds the comment
# line "# public key: age1..." plus the private key.
"${DC[@]}" run --rm --no-deps -T --entrypoint age-keygen backup > "${KEY}" 2>/dev/null
chmod 600 "${KEY}"
recipient="$(grep -oE 'age1[0-9a-z]+' "${KEY}" | head -1)"
[[ -n "${recipient}" ]] || { echo "FEHLER: kein age-recipient erzeugt"; exit 1; }
echo "BACKUP_AGE_RECIPIENT=${recipient}" >> .env

echo "==> postgres + minio hoch"
"${DC[@]}" up -d postgres minio
for i in $(seq 1 30); do
  "${DC[@]}" exec -T postgres pg_isready -U app -d antrag >/dev/null 2>&1 && break
  sleep 2
done

echo "==> Testdaten säen (DB-Zeile + MinIO-Objekt: ${MARKER})"
"${DC[@]}" exec -T postgres psql -U app -d antrag -c \
  "CREATE TABLE IF NOT EXISTS smoke(id text); INSERT INTO smoke VALUES ('${MARKER}');"
# Put the object into the bucket with mc, which only the backup image holds.
"${DC[@]}" run --rm --entrypoint bash backup -c "
  set -e
  source /opt/backup/lib.sh
  mc_env
  mc mb --ignore-existing \"\${MC_ALIAS}/\$(need MINIO_BUCKET)\" >/dev/null
  echo '${MARKER}' | mc pipe \"\${MC_ALIAS}/\$(need MINIO_BUCKET)/smoke.txt\" >/dev/null
"

echo "==> backup.sh"
"${DC[@]}" run --rm backup backup.sh

echo "==> Daten zerstören (DROP TABLE + Objekt löschen)"
"${DC[@]}" exec -T postgres psql -U app -d antrag -c "DROP TABLE smoke;"
"${DC[@]}" run --rm --entrypoint bash backup -c "
  set -e
  source /opt/backup/lib.sh
  mc_env
  mc rm \"\${MC_ALIAS}/\$(need MINIO_BUCKET)/smoke.txt\" >/dev/null
"

echo "==> restore.sh (FORCE, neuestes Artefakt)"
"${DC[@]}" run --rm -e FORCE=1 --entrypoint bash backup -c \
  'restore.sh "$(ls -t /backups/antrag-*.tar.age | head -1)"'

echo "==> Verifikation"
got_db="$("${DC[@]}" exec -T postgres psql -U app -d antrag -tAc \
  "SELECT id FROM smoke WHERE id='${MARKER}';" | tr -d '[:space:]')"
got_obj="$("${DC[@]}" run --rm --entrypoint bash backup -c "
  source /opt/backup/lib.sh; mc_env
  mc cat \"\${MC_ALIAS}/\$(need MINIO_BUCKET)/smoke.txt\"
" | tr -d '[:space:]')"

fail=0
[[ "${got_db}" == "${MARKER}" ]]  || { echo "FEHLER: DB-Zeile nicht wiederhergestellt ('${got_db}')"; fail=1; }
[[ "${got_obj}" == "${MARKER}" ]] || { echo "FEHLER: MinIO-Objekt nicht wiederhergestellt ('${got_obj}')"; fail=1; }

# Daemon and cron path. This step covers the exact run that the one-shot above SKIPS.
# The nightly run goes through crond (ash) plus /etc/backup.env. If the entrypoint writes
# the environment in bash syntax (`declare -x`), ash cannot source it. backup.sh then
# starts without POSTGRES_* and MINIO_*, and it writes no backup. The script sets the
# cron to every minute, starts the service as a daemon and waits for a NEW artifact.
echo "==> Daemon-/Cron-Pfad (crond + env-Datei)"
before="$("${DC[@]}" run --rm --no-deps --entrypoint bash backup \
  -c 'ls /backups/antrag-*.tar.age 2>/dev/null | wc -l' | tr -d '[:space:]')"
echo "BACKUP_CRON=* * * * *" >> .env          # env_file: the last key wins
"${DC[@]}" up -d backup
got_daemon=0
for _ in $(seq 1 30); do                       # max ~150s, the cron fires every minute
  now="$("${DC[@]}" exec -T backup sh -c 'ls /backups/antrag-*.tar.age 2>/dev/null | wc -l' | tr -d '[:space:]')"
  if [[ "${now:-0}" -gt "${before:-0}" ]]; then got_daemon=1; break; fi
  sleep 5
done
"${DC[@]}" stop backup >/dev/null 2>&1 || true
[[ "${got_daemon}" -eq 1 ]] || { echo "FEHLER: crond erzeugte kein Backup (env-Datei nicht ash-/bash-sourcebar?)"; fail=1; }

if [[ "${fail}" -eq 0 ]]; then
  echo "==> RESTORE-SMOKE OK — DB + MinIO wiederhergestellt; crond-Pfad erzeugt Backup."
else
  echo "==> RESTORE-SMOKE FEHLGESCHLAGEN."
  exit 1
fi
