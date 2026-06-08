#!/usr/bin/env bash
# E2E-Treiber (T-40): fährt den VOLLEN Stack via compose hoch (Mock AUS, echtes
# Backend/FE/pytex/Postgres/Redis/MinIO + mailpit als SMTP-Sink), seedet
# deterministische Fixtures und lässt Playwright gegen den echten ``web``-Endpunkt
# laufen. Räumt restlos ab (``down -v``). Idempotent; eigener Projektname → berührt
# andere Stacks NICHT.
#
# Deckt das deterministische, gate-bindende Subset ab (CI-Job `e2e`). Die noch
# offenen, flakeanfälligen/langsamen Szenarien (async Voting, Live-Vote-WS,
# Protokoll→PDF, OIDC) sind als Follow-up-Issues ausgelagert — siehe e2e/README.md.
#
# Usage: scripts/e2e.sh
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
# OIDC + Altcha im e2e-Stack AUS: die optionalen Secrets dürfen NICHT als leerer
# String gesetzt sein — `app.settings` validiert sie mit `min_length=16`, ein
# präsentes "" bricht `get_settings()` (→ migrate exit 1). `.env.example` shippt sie
# leer; hier die Zeilen entfernen ⇒ unset ⇒ Default None ⇒ Feature aus.
# (oidc_enabled/altcha_enabled werden False; /api/auth/login → 404 für den RBAC-Test.)
sed -i -E '/^[[:space:]]*(OIDC_CLIENT_SECRET|ALTCHA_HMAC_SECRET)[[:space:]]*=/d' "${ENV_FILE}"
# Overrides ans Ende → letzter Wert je Key gewinnt. Wegwerf-Secrets ≥16 Zeichen.
# Rate-Limit AUS → keine Lockouts; FORWARDED_ALLOW_IPS=* ok (environment=development).
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

echo "==> docker compose up -d --build"
if ! "${COMPOSE[@]}" up -d --build; then
  echo "FEHLER: compose up — Logs (migrate/api/web):"
  "${COMPOSE[@]}" logs --no-color --tail=120 migrate api web || true
  exit 1
fi

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
echo "==> Playwright"
cd "${FRONTEND}"
export E2E_BASE_URL="http://127.0.0.1:8080"
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
