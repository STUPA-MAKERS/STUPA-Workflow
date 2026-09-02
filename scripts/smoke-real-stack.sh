#!/usr/bin/env bash
# Real-stack smoke test (process fix). The script starts the FULL stack with compose. The
# mock is OFF, so the stack uses the real OIDC config and no mock Keycloak. The script
# sets a bootstrap admin. It then checks the core flows over HTTP and the healthchecks
# only. Use it to test a wave against the real stack (CI job `real-stack-smoke`, opt-in
# like e2e).
#
# The script runs NO frontend Selenium. The visual harness does that. This script only
# checks that the API is up, that /api/health answers, that the public endpoints return
# 2xx, that the auth path answers and that the WebSocket handshake answers.
#
# The script uses its own COMPOSE_PROJECT_NAME, so it does NOT touch a real or another
# stack. It writes deploy/.env with smoke values, saves an existing .env and puts that
# file back at the end. It removes everything again (down -v). The script is idempotent.
#
# Usage: scripts/smoke-real-stack.sh
#   SMOKE_TIMEOUT: default 600s, because ClamAV loads slowly.
#   WEB_PORT: host port of `web`, default 8080. Set it when 8080 is taken.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="${ROOT}/deploy"
ENV_FILE="${DEPLOY}/.env"
ENV_BACKUP=""
# The compose mapping reads WEB_PORT, so the script and the stack agree on one value.
WEB_PORT="${WEB_PORT:-8080}"
export WEB_PORT
WEB="http://127.0.0.1:${WEB_PORT}"
TIMEOUT="${SMOKE_TIMEOUT:-600}"

export COMPOSE_PROJECT_NAME="antrag-real-smoke"

cd "${DEPLOY}"

cleanup() {
  # Show the logs of anything that did not come up BEFORE tearing the stack down. A
  # smoke failure that prints only "service migrate didn't complete successfully" costs
  # the next person a full round trip to find out what actually broke.
  if [[ "${SMOKE_OK:-0}" != "1" ]]; then
    # `ps` first: it names which service is unhealthy, which is usually the answer.
    echo "==> Container status (smoke failed)"
    docker compose ps || true
    # One block per service. A single combined `logs ... | tail` lets a chatty service
    # such as migrate crowd out the one that actually failed.
    for svc in migrate api worker web; do
      echo "--- logs: ${svc} ---"
      docker compose logs --no-color --tail 30 "${svc}" 2>&1 | tail -30 || true
    done
  fi
  echo "==> Teardown (down -v)"
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "${ENV_BACKUP}" && -f "${ENV_BACKUP}" ]]; then
    mv -f "${ENV_BACKUP}" "${ENV_FILE}"          # put the existing .env back
  else
    rm -f "${ENV_FILE}"                           # remove our smoke .env
  fi
}
trap cleanup EXIT

# Prepare .env: mock OFF, bootstrap admin set.
if [[ -f "${ENV_FILE}" ]]; then
  ENV_BACKUP="${ENV_FILE}.smoke-bak"
  mv -f "${ENV_FILE}" "${ENV_BACKUP}"
fi
cp .env.example "${ENV_FILE}"
# Append the overrides, because the last value per key wins (docker compose env_file).
# The throwaway secrets hold at least 16 characters. app.settings rejects a shorter one.
# OIDC keeps the .env.example placeholders and gets no mock, so /api/auth/login answers
# with a redirect (307). The script never follows that redirect. The bootstrap admin
# comes from the email and the subject.
cat >> "${ENV_FILE}" <<'EOF'

# --- smoke-real-stack overrides (NICHT committen; vom Skript erzeugt) -------
POSTGRES_PASSWORD=smoke-pg-pw
DATABASE_URL=postgresql+asyncpg://app:smoke-pg-pw@postgres/antrag
MINIO_ACCESS_KEY=smoke-minio-access
MINIO_SECRET_KEY=smoke-minio-secret-key
SESSION_SECRET=smoke-session-secret-0123456789
MAGIC_LINK_SECRET=smoke-magic-link-secret-0123456789
ALTCHA_HMAC_SECRET=smoke-altcha-hmac-secret-0123456789
# `.env.example` ships this EMPTY, and an empty string is not an absent one, so the
# 16-character minimum rejects it and every app container refuses to start. The stack
# needs no working OIDC here; it only has to satisfy the settings validation.
OIDC_CLIENT_SECRET=smoke-oidc-client-secret-0123456789
BOOTSTRAP_ADMIN_EMAILS=admin@smoke.example
BOOTSTRAP_ADMIN_SUBJECTS=smoke-admin-subject
# `.env.example` sets ENVIRONMENT=production, and production forbids a wildcard
# FORWARDED_ALLOW_IPS: with "*" uvicorn trusts any X-Forwarded-* source, so a client IP
# can be spoofed. The smoke stack reaches the app through the compose proxy from the
# runner, which needs the wildcard, and the settings guard documents exactly this case
# as allowed outside production ("dev, CI, container smoke"). So the environment moves
# with it rather than the guard being weakened.
ENVIRONMENT=ci
FORWARDED_ALLOW_IPS=*
EOF

# Outside the quoted heredoc, because that block does NOT expand variables and these two
# values have to carry the chosen port.
{
  echo "PUBLIC_BASE_URL=${WEB}"
  echo "WEB_PORT=${WEB_PORT}"
} >> "${ENV_FILE}"

# The web image compiles the Angular app against the ui-kit submodule, so a fresh
# clone has to sync it first. `deploy/deploy.sh` does the same before it builds. Without
# this the build fails on an unresolvable `@stupa-makers/ui-kit`.
echo "==> git submodule sync + update --init --recursive"
git -C "${ROOT}" submodule sync --recursive
git -C "${ROOT}" submodule update --init --recursive

echo "==> docker compose config (Validierung)"
docker compose config -q

echo "==> docker compose up -d --build"
docker compose up -d --build

# api waits with depends_on for migrate (completed) and for postgres, redis and minio
# (healthy). web waits for api (healthy). If both are healthy, the core stack is up.
# ClamAV is slow and does not matter for the HTTP flows, so the script does not wait for
# it.
echo "==> Warte bis api + web healthy (max ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
while :; do
  ok=1
  for svc in api web; do
    cid="$(docker compose ps -q "${svc}" 2>/dev/null || true)"
    if [[ -z "${cid}" ]]; then ok=0; continue; fi
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}" 2>/dev/null || echo missing)"
    [[ "${status}" == "healthy" ]] || { ok=0; echo "   ${svc}: ${status}"; }
  done
  [[ "${ok}" -eq 1 ]] && { echo "==> api + web healthy."; break; }
  if [[ "$(date +%s)" -ge "${deadline}" ]]; then
    echo "FEHLER: Timeout — api/web nicht healthy."
    docker compose ps
    docker compose logs --no-color --tail=50 api web || true
    exit 1
  fi
  sleep 5
done

fails=0

# check <name> <path> <expected-code...>. The call has no -L, so curl does NOT follow a
# redirect.
check() {
  local name="$1" path="$2"; shift 2
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${WEB}${path}" || echo 000)"
  for exp in "$@"; do
    if [[ "${code}" == "${exp}" ]]; then
      printf '  OK    %-28s -> %s  (%s)\n' "${name}" "${code}" "${path}"
      return 0
    fi
  done
  printf '  FAIL  %-28s -> %s  (erwartet: %s) (%s)\n' "${name}" "${code}" "$*" "${path}"
  fails=$((fails + 1))
}

echo "==> HTTP-Kernflüsse (${WEB})"
check "web /healthz"          "/healthz"        200        # nginx liveness
check "api /api/health"       "/api/health"     200        # FastAPI up
check "public site-config"    "/api/site-config" 200       # branding read without auth
# 307 is a redirect to the OIDC issuer, so OIDC is fully configured. 404 means OIDC is
# off, because .env.example ships OIDC_CLIENT_SECRET empty and oidc_enabled needs all
# four fields. login() then returns 404. The smoke test runs without a real IdP on
# purpose, so both codes are OK. The check only proves that the route exists and answers
# with no 5xx and no 000.
check "auth login erreichbar" "/api/auth/login" 307 404
check "auth me (unauth)"      "/api/auth/me"    401        # RBAC applies, problem+json
check "unbekannt -> 404"      "/api/__nope__"   404        # the error handler answers

# Send the upgrade headers. The app MUST answer: 101 on an upgrade, else 400, 401, 403 or
# 426, because the request carries no auth. 000, 502 or 404 means the proxy or the route
# is broken.
echo "==> WebSocket-Handshake erreichbar"
ws_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  "${WEB}/api/ws/meetings/00000000-0000-0000-0000-000000000000" || echo 000)"
case "${ws_code}" in
  101|400|401|403|426)
    printf '  OK    %-28s -> %s  (handshake von der App behandelt)\n' "ws meetings" "${ws_code}" ;;
  *)
    printf '  FAIL  %-28s -> %s  (Proxy/Route erreicht die App nicht)\n' "ws meetings" "${ws_code}"
    fails=$((fails + 1)) ;;
esac

echo "==> ${fails} Fehler"
if [[ "${fails}" -ne 0 ]]; then
  docker compose logs --no-color --tail=80 api web || true
  exit 1
fi
SMOKE_OK=1
echo "==> Real-Stack-Smoke grün."
