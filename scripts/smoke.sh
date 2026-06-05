#!/usr/bin/env bash
# Smoke-Test (T-01): bringt den Stack hoch und prüft, dass alle Services healthy
# werden. Zählt als "Test" dieser Infra-Task (T-01 AK).
#
# Usage: scripts/smoke.sh [up|down]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="${ROOT}/deploy"
TIMEOUT="${SMOKE_TIMEOUT:-420}"   # ClamAV-DB-Load braucht Zeit

cd "${COMPOSE_DIR}"

if [[ ! -f .env ]]; then
  echo "Kein deploy/.env — kopiere .env.example -> .env (Platzhalterwerte)."
  cp .env.example .env
fi

down() { docker compose down -v --remove-orphans; }

case "${1:-up}" in
  down) down; exit 0 ;;
esac

echo "==> docker compose config (Validierung)"
docker compose config -q

echo "==> docker compose up -d --build"
docker compose up -d --build

echo "==> Warte bis alle Services healthy (max ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
services="$(docker compose config --services)"

while :; do
  unhealthy=0
  for svc in ${services}; do
    cid="$(docker compose ps -q "${svc}" || true)"
    [[ -z "${cid}" ]] && { unhealthy=1; continue; }
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${cid}" 2>/dev/null || echo missing)"
    case "${status}" in
      healthy|running) ;;   # running = Service ohne Healthcheck (z.B. altcha-Platzhalter)
      *) unhealthy=1; echo "   ${svc}: ${status}" ;;
    esac
  done
  [[ "${unhealthy}" -eq 0 ]] && { echo "==> Alle Services healthy."; exit 0; }
  if [[ "$(date +%s)" -ge "${deadline}" ]]; then
    echo "FEHLER: Timeout — nicht alle Services healthy."
    docker compose ps
    exit 1
  fi
  sleep 5
done
