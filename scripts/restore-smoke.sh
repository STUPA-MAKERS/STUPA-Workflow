#!/usr/bin/env bash
# Restore smoke test. The script proves the backup and restore round trip against a
# throwaway stack:
#   postgres + redis + minio + migrate -> seed a DB row AND a MinIO object ->
#   create a backup -> destroy both -> restore -> check that both come back.
#
# Backups run inside the application, so the script drives the real `BackupService` and
# the real worker tasks inside the `api` container, against a real Postgres and a real
# MinIO. It does NOT go through the HTTP routes: those need an OIDC login, and the unit
# tests already cover the routing and the RBAC. What only a live stack can prove is the
# part this script exercises — that `pg_dump` and `pg_restore` are present and match the
# server major, that the age round trip works on real bytes, and that the bucket mirror
# puts the objects back.
#
# The script creates an EPHEMERAL age key pair inside the throwaway stack and deletes it
# again. It removes the whole stack at the end (down -v). Each run starts fresh, so the
# script is idempotent.
#
# Usage: scripts/restore-smoke.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="${ROOT}/deploy"
SECRETS="${DEPLOY}/secrets"
KEY="${SECRETS}/backup-age.key"
MARKER="restore-smoke-$(date -u +%s)"

cd "${DEPLOY}"

# The script uses its own compose project, so it does not touch a real stack.
export COMPOSE_PROJECT_NAME="antrag-restore-smoke"
DC=(docker compose)

# Every service has `env_file: .env`, so deploy/.env must exist. The script moves a real
# .env aside and puts it back at the end, so the smoke test overwrites nothing.
ENV_BAK=""
cleanup() {
  "${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "${KEY}"
  rm -f "${DEPLOY}/.env"
  [[ -n "${ENV_BAK}" ]] && mv "${ENV_BAK}" "${DEPLOY}/.env"
}
trap cleanup EXIT

echo "==> prepare .env"
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
  echo "SESSION_SECRET=smoke-session-secret-that-is-long-enough-000000"
  echo "MAGIC_LINK_SECRET=smoke-magic-secret-that-is-long-enough-0000000"
} >> .env

echo "==> build the backend image"
"${DC[@]}" build api >/dev/null

echo "==> generate an ephemeral age key pair"
mkdir -p "${SECRETS}"
# `pyrage` ships with the backend, so the key pair comes from the same library that
# writes the archives. The private key stays on the HOST, because the container mounts
# /secrets read-only.
"${DC[@]}" run --rm --no-deps -T --entrypoint python api -c '
from pyrage import x25519
identity = x25519.Identity.generate()
print(f"# public key: {identity.to_public()}")
print(identity)
' > "${KEY}"
chmod 600 "${KEY}"
recipient="$(grep -oE 'age1[0-9a-z]+' "${KEY}" | head -1)"
[[ -n "${recipient}" ]] || { echo "ERROR: no age recipient was generated"; exit 1; }
echo "BACKUP_AGE_RECIPIENT=${recipient}" >> .env

echo "==> start postgres, redis and minio"
"${DC[@]}" up -d postgres redis minio
for _ in $(seq 1 30); do
  "${DC[@]}" exec -T postgres pg_isready -U app -d antrag >/dev/null 2>&1 && break
  sleep 2
done

echo "==> migrate"
"${DC[@]}" up migrate --exit-code-from migrate >/dev/null

echo "==> seed a DB row and a MinIO object (${MARKER})"
"${DC[@]}" exec -T postgres psql -U app -d antrag -c \
  "CREATE TABLE IF NOT EXISTS smoke(id text); INSERT INTO smoke VALUES ('${MARKER}');"
"${DC[@]}" run --rm --no-deps -T --entrypoint python api -c "
import asyncio
from app.modules.files.storage import build_object_storage
from app.settings import load_settings
storage = build_object_storage(load_settings())
asyncio.run(storage.put('smoke.txt', b'${MARKER}', 'text/plain'))
print('seeded the object')
"

# One helper drives both directions. `create_backup` and `restore_backup` are the exact
# functions the arq worker registers, so the smoke test covers the shipped code path
# rather than a re-implementation of it.
run_task() {
  "${DC[@]}" run --rm -T --entrypoint python api -c "$1"
}

echo "==> create a backup"
backup_id="$(run_task "
import asyncio
from app.db import get_sessionmaker
from app.modules.backup.service import BackupService
from app.modules.files.storage import build_object_storage
from app.settings import load_settings
from worker.backup import create_backup

settings = load_settings()

async def main() -> None:
    maker = get_sessionmaker()
    async with maker() as session:
        service = BackupService(session, settings)
        row = await service.create_row(kind='manual', actor='smoke', note=None)
        await session.commit()
        backup_id = str(row.id)
    ctx = {
        'backup_settings': settings,
        'backup_attachments': build_object_storage(settings),
        'backup_archives': build_object_storage(settings, bucket=settings.backup_bucket),
    }
    outcome = await create_backup(ctx, backup_id)
    assert outcome == 'done', f'backup failed: {outcome}'
    print(backup_id)

asyncio.run(main())
" | tail -1 | tr -d '[:space:]')"
[[ -n "${backup_id}" ]] || { echo "ERROR: no backup was created"; exit 1; }
echo "    backup ${backup_id}"

echo "==> destroy the data (DROP TABLE + remove the object)"
"${DC[@]}" exec -T postgres psql -U app -d antrag -c "DROP TABLE smoke;"
"${DC[@]}" run --rm --no-deps -T --entrypoint python api -c "
import asyncio
from app.modules.files.storage import build_object_storage
from app.settings import load_settings
storage = build_object_storage(load_settings())
asyncio.run(storage.remove('smoke.txt'))
print('removed the object')
"

echo "==> restore"
run_task "
import asyncio
from app.modules.files.storage import build_object_storage
from app.settings import load_settings
from worker.backup import restore_backup

settings = load_settings()
ctx = {
    'backup_settings': settings,
    'backup_attachments': build_object_storage(settings),
    'backup_archives': build_object_storage(settings, bucket=settings.backup_bucket),
}
outcome = asyncio.run(restore_backup(ctx, '${backup_id}', 'smoke'))
assert outcome == 'done', f'restore failed: {outcome}'
print('restored')
" >/dev/null

echo "==> verify"
got_db="$("${DC[@]}" exec -T postgres psql -U app -d antrag -tAc \
  "SELECT id FROM smoke WHERE id='${MARKER}';" | tr -d '[:space:]')"
got_obj="$("${DC[@]}" run --rm --no-deps -T --entrypoint python api -c "
import asyncio
from app.modules.files.storage import build_object_storage
from app.settings import load_settings
storage = build_object_storage(load_settings())
print(asyncio.run(storage.get('smoke.txt')).decode())
" | tr -d '[:space:]')"

fail=0
[[ "${got_db}" == "${MARKER}" ]] || {
  echo "ERROR: the DB row did not come back ('${got_db}')"; fail=1
}
[[ "${got_obj}" == "${MARKER}" ]] || {
  echo "ERROR: the MinIO object did not come back ('${got_obj}')"; fail=1
}

# The restore must have left a safety archive behind. That copy is the only undo for a
# restore of the wrong archive, so its absence is a failure even when the data is back.
safety="$("${DC[@]}" exec -T postgres psql -U app -d antrag -tAc \
  "SELECT count(*) FROM backup WHERE kind='pre_restore' AND status='done';" \
  | tr -d '[:space:]')"
[[ "${safety}" == "1" ]] || {
  echo "ERROR: the restore left no pre_restore safety archive (found '${safety}')"; fail=1
}

if [[ "${fail}" -eq 0 ]]; then
  echo "==> RESTORE-SMOKE OK — DB and MinIO restored, safety archive present."
else
  echo "==> RESTORE-SMOKE FAILED."
  exit 1
fi
