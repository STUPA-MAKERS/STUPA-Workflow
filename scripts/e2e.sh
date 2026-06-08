#!/usr/bin/env bash
# E2E-Treiber (T-40): fährt den VOLLEN Stack via compose hoch (Mock AUS, echtes
# Backend/FE/pytex/Postgres/Redis/MinIO + mailpit als SMTP-Sink), seedet
# deterministische Fixtures und lässt Playwright gegen den echten ``web``-Endpunkt
# laufen. Räumt restlos ab (``down -v``). Idempotent; eigener Projektname → berührt
# andere Stacks NICHT.
#
# Tiers:
#   (default)  gating  — stabiler, deterministischer Subset (CI-Gate, jeder PR).
#   --full / E2E_FULL=1 full — zusätzlich die opt-in/flakeanfälligen Szenarien
#                              (Live-Vote-WS, Protokoll→PDF). Nicht gate-bindend.
#
# Usage: scripts/e2e.sh [--full]
#   E2E_TIMEOUT (Default 900s; Image-Build + ClamAV-Start). Host-Ports fix:
#   web 127.0.0.1:8080 (compose), mailpit-API 127.0.0.1:8025 (overlay).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="${ROOT}/deploy"
FRONTEND="${ROOT}/frontend"
ENV_FILE="${DEPLOY}/.env"
ENV_BACKUP=""
ARTIFACTS="${DEPLOY}/e2e/.artifacts"
TIMEOUT="${E2E_TIMEOUT:-900}"

TIER="gating"
if [[ "${1:-}" == "--full" || "${E2E_FULL:-0}" == "1" ]]; then
  TIER="full"
fi

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

# --- .env vorbereiten (Mock AUS, mailpit-SMTP, Anti-Abuse aus für Determinismus) --- #
if [[ -f "${ENV_FILE}" ]]; then
  ENV_BACKUP="${ENV_FILE}.e2e-bak"
  mv -f "${ENV_FILE}" "${ENV_BACKUP}"
fi
cp .env.example "${ENV_FILE}"
# Overrides ans Ende → letzter Wert je Key gewinnt. Wegwerf-Secrets ≥16 Zeichen.
# OIDC bleibt unkonfiguriert (kein Mock-Keycloak) → Login 404 (RBAC-Negativtest).
# Altcha AUS (ALTCHA_HMAC_SECRET leer) + Rate-Limit AUS → keine Flakes/Lockouts.
cat >> "${ENV_FILE}" <<'EOF'

# --- e2e overrides (vom Treiber erzeugt; NICHT committen) ----------------------
POSTGRES_PASSWORD=e2e-pg-pw
DATABASE_URL=postgresql+asyncpg://app:e2e-pg-pw@postgres/antrag
MINIO_ACCESS_KEY=e2e-minio-access
MINIO_SECRET_KEY=e2e-minio-secret-key
SESSION_SECRET=e2e-session-secret-0123456789
MAGIC_LINK_SECRET=e2e-magic-link-secret-0123456789
ALTCHA_HMAC_SECRET=
RATE_LIMIT_ENABLED=false
FORWARDED_ALLOW_IPS=*
PUBLIC_BASE_URL=http://127.0.0.1:8080
# mailpit als SMTP-Sink (kein TLS).
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_STARTTLS=false
SMTP_SSL=false
SMTP_FROM=noreply@e2e.test
EOF

rm -rf "${ARTIFACTS}"; mkdir -p "${ARTIFACTS}"

echo "==> docker compose config (Validierung)"
"${COMPOSE[@]}" config -q

echo "==> docker compose up -d --build (Tier: ${TIER})"
"${COMPOSE[@]}" up -d --build

# --- warten bis api + web + mailpit healthy -------------------------------- #
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

# --- deterministisch seeden ------------------------------------------------ #
echo "==> Seed (Form-/Flow-Version, Admin-Session, Budget-Topf)"
"${COMPOSE[@]}" run --rm seed
if [[ ! -s "${ARTIFACTS}/e2e.json" ]]; then
  echo "FEHLER: Seed-Artefakt ${ARTIFACTS}/e2e.json fehlt."
  exit 1
fi

# --- Playwright ------------------------------------------------------------ #
echo "==> Playwright (Tier: ${TIER})"
cd "${FRONTEND}"
export E2E_BASE_URL="http://127.0.0.1:8080"
export E2E_MAILPIT_URL="http://127.0.0.1:8025"
export E2E_ARTIFACTS_FILE="${ARTIFACTS}/e2e.json"

pw_args=()
if [[ "${TIER}" == "gating" ]]; then
  pw_args+=(--grep-invert @full)
fi

set +e
npx playwright test "${pw_args[@]}"
rc=$?
set -e

if [[ "${rc}" -ne 0 ]]; then
  echo "==> Playwright rot — Compose-Logs (api/web/worker):"
  cd "${DEPLOY}"
  "${COMPOSE[@]}" logs --no-color --tail=120 api web worker || true
fi

exit "${rc}"
