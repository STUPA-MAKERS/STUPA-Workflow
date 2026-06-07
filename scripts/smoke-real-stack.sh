#!/usr/bin/env bash
# Real-Stack-Smoke (Prozess-Fix): fährt den VOLLEN Stack via compose hoch —
# Mock AUS (echte OIDC-Config, kein Mock-Keycloak), Bootstrap-Admin gesetzt — und
# prüft die Kernflüsse rein über HTTP/Healthcheck. Gedacht, um eine Welle bewusst
# gegen den echten Stack zu testen (CI-Job `real-stack-smoke`, opt-in wie e2e).
#
# KEIN FE-Selenium hier — das macht die Visual-Harness. Hier nur: API up,
# /api/health, öffentliche Endpunkte 2xx, Auth-Pfad erreichbar, WS-Handshake
# erreichbar.
#
# Eigener COMPOSE_PROJECT_NAME -> berührt einen echten/anderen Stack NICHT.
# Schreibt temporär deploy/.env (Smoke-Werte), sichert ein vorhandenes .env und
# stellt es am Ende wieder her. Räumt restlos ab (down -v). Idempotent.
#
# Usage: scripts/smoke-real-stack.sh
#   SMOKE_WEB_PORT (Default 8080) · SMOKE_TIMEOUT (Default 600s; ClamAV lädt lange)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="${ROOT}/deploy"
ENV_FILE="${DEPLOY}/.env"
ENV_BACKUP=""
PORT="${SMOKE_WEB_PORT:-8080}"
WEB="http://127.0.0.1:${PORT}"
TIMEOUT="${SMOKE_TIMEOUT:-600}"

export COMPOSE_PROJECT_NAME="antrag-real-smoke"

cd "${DEPLOY}"

cleanup() {
  echo "==> Teardown (down -v)"
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "${ENV_BACKUP}" && -f "${ENV_BACKUP}" ]]; then
    mv -f "${ENV_BACKUP}" "${ENV_FILE}"          # vorhandenes .env zurück
  else
    rm -f "${ENV_FILE}"                           # unser Smoke-.env weg
  fi
}
trap cleanup EXIT

# --- .env vorbereiten (Mock AUS, Bootstrap-Admin gesetzt) ------------------- #
if [[ -f "${ENV_FILE}" ]]; then
  ENV_BACKUP="${ENV_FILE}.smoke-bak"
  mv -f "${ENV_FILE}" "${ENV_BACKUP}"
fi
cp .env.example "${ENV_FILE}"
# Overrides ans Ende -> letzter Wert je Key gewinnt (docker compose env_file).
# Wegwerf-Secrets (≥16 Zeichen, sonst lehnt app.settings ab); OIDC bleibt auf den
# .env.example-Platzhaltern (kein Mock) -> /api/auth/login redirected (307), wird
# nie gefolgt. Bootstrap-Admin per E-Mail + Subject gesetzt.
cat >> "${ENV_FILE}" <<'EOF'

# --- smoke-real-stack overrides (NICHT committen; vom Skript erzeugt) -------
POSTGRES_PASSWORD=smoke-pg-pw
DATABASE_URL=postgresql+asyncpg://app:smoke-pg-pw@postgres/antrag
MINIO_ACCESS_KEY=smoke-minio-access
MINIO_SECRET_KEY=smoke-minio-secret-key
SESSION_SECRET=smoke-session-secret-0123456789
MAGIC_LINK_SECRET=smoke-magic-link-secret-0123456789
ALTCHA_HMAC_SECRET=smoke-altcha-hmac-secret-0123456789
BOOTSTRAP_ADMIN_EMAILS=admin@smoke.example
BOOTSTRAP_ADMIN_SUBJECTS=smoke-admin-subject
FORWARDED_ALLOW_IPS=*
PUBLIC_BASE_URL=http://127.0.0.1:8080
EOF

echo "==> docker compose config (Validierung)"
docker compose config -q

echo "==> docker compose up -d --build"
docker compose up -d --build

# --- warten bis api + web healthy ------------------------------------------ #
# api hängt via depends_on an migrate(completed)+postgres/redis/minio(healthy);
# web an api(healthy). Sind beide healthy, steht der Kern-Stack. ClamAV (langsam)
# ist für die HTTP-Flüsse irrelevant -> nicht abgewartet.
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

# --- Kernflüsse prüfen ------------------------------------------------------ #
fails=0

# check <name> <pfad> <erwarteter-code...>  (kein -L: Redirects NICHT folgen)
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
check "web /healthz"          "/healthz"        200        # nginx-Liveness
check "api /api/health"       "/api/health"     200        # FastAPI up
check "public site-config"    "/api/site-config" 200       # auth-freier Branding-Read
check "auth login erreichbar" "/api/auth/login" 307        # Redirect zur OIDC-Issuer
check "auth me (unauth)"      "/api/auth/me"    401        # RBAC greift, problem+json
check "unbekannt -> 404"      "/api/__nope__"   404        # Error-Handler erreichbar

# WS-Handshake erreichbar: Upgrade-Header senden; die App MUSS antworten (101 bei
# Upgrade, sonst 401/403/426/400 weil unauth). 000/502/404 => Proxy/Route kaputt.
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
echo "==> Real-Stack-Smoke grün."
