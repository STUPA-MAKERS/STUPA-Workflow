#!/usr/bin/env bash
# E2E driver (T-40). The script starts the FULL stack with compose. The mock is OFF, so
# the stack runs the real backend, frontend, pytex, Postgres, Redis and MinIO, plus
# mailpit as the SMTP sink. The script seeds deterministic fixtures. It then runs
# Playwright against the real `web` endpoint. It removes everything again (`down -v`).
# The script is idempotent. It uses its own project name, so it does NOT touch another
# stack.
#
# The script covers the deterministic subset that binds the gate (CI job `e2e`). The
# open scenarios that are slow or flaky moved to follow-up issues: async voting,
# live-vote WebSocket, protocol to PDF and OIDC. See e2e/README.md.
#
# Usage: scripts/e2e.sh
#   E2E_TIMEOUT: default 900s, for the image build and the ClamAV start.
#   WEB_PORT: host port of `web`, default 8080. The mailpit API stays on
#   127.0.0.1:8025 (overlay).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The compose mapping reads WEB_PORT, so the script and the stack agree on one value.
WEB_PORT="${WEB_PORT:-8080}"
export WEB_PORT
WEB="http://127.0.0.1:${WEB_PORT}"
DEPLOY="${ROOT}/deploy"
FRONTEND="${ROOT}/frontend"
ENV_FILE="${DEPLOY}/.env"
ENV_BACKUP=""
ARTIFACTS="${DEPLOY}/e2e/.artifacts"
TIMEOUT="${E2E_TIMEOUT:-900}"

export COMPOSE_PROJECT_NAME="antrag-e2e"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.e2e.yml)

cd "${DEPLOY}"

cleanup() {
  echo "==> Teardown (down -v)"
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "${ENV_BACKUP}" && -f "${ENV_BACKUP}" ]]; then
    mv -f "${ENV_BACKUP}" "${ENV_FILE}"
  else
    rm -f "${ENV_FILE}"
  fi
  rm -rf "${ARTIFACTS}"
}
trap cleanup EXIT

# Prepare .env: mock OFF, mailpit SMTP, anti-abuse off to keep the run deterministic.
if [[ -f "${ENV_FILE}" ]]; then
  ENV_BACKUP="${ENV_FILE}.e2e-bak"
  mv -f "${ENV_FILE}" "${ENV_BACKUP}"
fi
cp .env.example "${ENV_FILE}"
# OIDC and ALTCHA stay OFF in the e2e stack. The optional secrets must NOT hold an empty
# string. `app.settings` validates them with `min_length=16`. A present "" breaks
# `get_settings()`, and migrate exits with 1. `.env.example` ships the keys empty. This
# sed removes the lines. The keys stay unset, fall back to None and turn the feature off.
# oidc_enabled and altcha_enabled become False. /api/auth/login then returns 404, which
# the RBAC test needs.
sed -i -E '/^[[:space:]]*(OIDC_CLIENT_SECRET|ALTCHA_HMAC_SECRET)[[:space:]]*=/d' "${ENV_FILE}"
# Append the overrides, because the last value per key wins. The throwaway secrets hold
# at least 16 characters. The rate limit is OFF, so no lockout can happen.
# The value `FORWARDED_ALLOW_IPS=*` is safe here, because the environment is development.
cat >> "${ENV_FILE}" <<'EOF'

# --- e2e overrides (vom Treiber erzeugt; NICHT committen) ----------------------
POSTGRES_PASSWORD=e2e-pg-pw
DATABASE_URL=postgresql+asyncpg://app:e2e-pg-pw@postgres/antrag
MINIO_ACCESS_KEY=e2e-minio-access
MINIO_SECRET_KEY=e2e-minio-secret-key
SESSION_SECRET=e2e-session-secret-0123456789
MAGIC_LINK_SECRET=e2e-magic-link-secret-0123456789
RATE_LIMIT_ENABLED=false
FORWARDED_ALLOW_IPS=*
# mailpit als SMTP-Sink (kein TLS).
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_STARTTLS=false
SMTP_SSL=false
SMTP_FROM=noreply@e2e.test
EOF

# Outside the quoted heredoc, because that block does NOT expand variables and these two
# values have to carry the chosen port.
{
  echo "PUBLIC_BASE_URL=${WEB}"
  echo "WEB_PORT=${WEB_PORT}"
} >> "${ENV_FILE}"

rm -rf "${ARTIFACTS}"; mkdir -p "${ARTIFACTS}"

echo "==> docker compose config (Validierung)"
"${COMPOSE[@]}" config -q

echo "==> docker compose up -d --build"
if ! "${COMPOSE[@]}" up -d --build; then
  echo "FEHLER: compose up — Logs (migrate/api/web):"
  "${COMPOSE[@]}" logs --no-color --tail=120 migrate api web || true
  exit 1
fi

echo "==> Warte bis api + web + mailpit healthy (max ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
while :; do
  ok=1
  for svc in api web mailpit; do
    cid="$("${COMPOSE[@]}" ps -q "${svc}" 2>/dev/null || true)"
    if [[ -z "${cid}" ]]; then ok=0; continue; fi
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}" 2>/dev/null || echo missing)"
    [[ "${status}" == "healthy" ]] || { ok=0; echo "   ${svc}: ${status}"; }
  done
  [[ "${ok}" -eq 1 ]] && { echo "==> api + web + mailpit healthy."; break; }
  if [[ "$(date +%s)" -ge "${deadline}" ]]; then
    echo "FEHLER: Timeout — Stack nicht healthy."
    "${COMPOSE[@]}" ps
    "${COMPOSE[@]}" logs --no-color --tail=60 api web mailpit migrate || true
    exit 1
  fi
  sleep 5
done

echo "==> Seed (Form-/Flow-Version, Admin-Session, Budget-Topf)"
"${COMPOSE[@]}" run --rm seed
if [[ ! -s "${ARTIFACTS}/e2e.json" ]]; then
  echo "FEHLER: Seed-Artefakt ${ARTIFACTS}/e2e.json fehlt."
  exit 1
fi

echo "==> Playwright"
cd "${FRONTEND}"
export E2E_BASE_URL="${WEB}"
export E2E_MAILPIT_URL="http://127.0.0.1:8025"
export E2E_ARTIFACTS_FILE="${ARTIFACTS}/e2e.json"

set +e
npx playwright test
rc=$?
set -e

if [[ "${rc}" -ne 0 ]]; then
  echo "==> Playwright rot — Compose-Logs (api/web/worker):"
  cd "${DEPLOY}"
  "${COMPOSE[@]}" logs --no-color --tail=120 api web worker || true
fi

exit "${rc}"
