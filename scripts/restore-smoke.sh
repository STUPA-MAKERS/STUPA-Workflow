#!/usr/bin/env bash
# Restore-Smoke (T-42 AK): beweist die Backup->Restore-Runde in einem Wegwerf-Stack.
#   postgres+minio hoch -> Testdaten säen -> backup.sh -> Daten zerstören ->
#   restore.sh -> prüfen, dass DB-Zeile UND MinIO-Objekt zurück sind.
# Nutzt eine EPHEMERE age-Schlüsseldatei (im Wegwerf-Stack erzeugt, danach gelöscht).
# Räumt am Ende restlos ab (down -v). Idempotent: jeder Lauf startet frisch.
#
# Usage: scripts/restore-smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="${ROOT}/deploy"
SECRETS="${DEPLOY}/backup/secrets"
KEY="${SECRETS}/age.key"
MARKER="restore-smoke-$(date -u +%s)"

cd "${DEPLOY}"

# Eigenes Projekt -> berührt einen echten Stack nicht.
export COMPOSE_PROJECT_NAME="antrag-restore-smoke"
DC=(docker compose --profile backup)

# Die backup-Service-Definition hat `env_file: .env` -> deploy/.env muss existieren
# (für Substitution UND Container-Env). Ein vorhandenes echtes .env beiseitelegen
# und am Ende zurückspielen, damit der Smoke nichts überschreibt.
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
# Platzhalter mit funktionierenden Smoke-Werten füllen.
{
  echo "POSTGRES_PASSWORD=smokepw"
  echo "MINIO_ACCESS_KEY=smokeaccess"
  echo "MINIO_SECRET_KEY=smokesecret123"
} >> .env

echo "==> backup-Image bauen"
"${DC[@]}" build backup >/dev/null

echo "==> ephemeres age-Schlüsselpaar erzeugen"
mkdir -p "${SECRETS}"
# age-keygen liegt im backup-Image. Nach STDOUT erzeugen und auf den HOST schreiben
# (/secrets ist im Container read-only gemountet). Die Ausgabe enthält die
# Kommentarzeile "# public key: age1..." plus den privaten Key.
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
# Objekt über das backup-Image (mc) in den Bucket legen.
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

# --- Daemon-/Cron-Pfad: deckt genau den Lauf ab, den der One-Shot oben UMGEHT. ---
# Der nächtliche Lauf geht über crond (ash) + /etc/backup.env. Schreibt der
# entrypoint die env in bash-Syntax (`declare -x`), kann ash sie nicht sourcen und
# backup.sh startet ohne POSTGRES_*/MINIO_* -> kein Backup. Wir setzen die Cron auf
# jede Minute, starten den Service als Daemon und warten auf ein NEUES Artefakt.
echo "==> Daemon-/Cron-Pfad (crond + env-Datei)"
before="$("${DC[@]}" run --rm --no-deps --entrypoint bash backup \
  -c 'ls /backups/antrag-*.tar.age 2>/dev/null | wc -l' | tr -d '[:space:]')"
echo "BACKUP_CRON=* * * * *" >> .env          # env_file: letzter Key gewinnt
"${DC[@]}" up -d backup
got_daemon=0
for _ in $(seq 1 30); do                       # max ~150s (Cron feuert minütlich)
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
