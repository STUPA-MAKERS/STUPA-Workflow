#!/usr/bin/env bash
# Deploy-Update (prod): pull -> build -> nur geänderte Container neu starten.
#
# Ablauf:
#   1. git pull (--ff-only) im Repo-Root.
#   2. Alle build-Services bauen (Layer-Cache macht unveränderte Builds quasi gratis).
#   3. Pro build-Service die Image-ID vor/nach dem Build vergleichen; nur Services mit
#      geänderter Image-ID per `up -d` neu erzeugen. Unveränderte (und alle Daten-
#      Services: postgres/redis/minio/clamav/altcha) bleiben unberührt.
#
# Scope: --profile prod (inkl. backup), passend zu deploy/README.md.
#
# Grenze: Erkennung läuft über die Image-ID. Eine Änderung, die NUR die compose-Config
# oder .env eines image-only-Services betrifft (z. B. ein postgres-env-Tweak), wird hier
# NICHT erfasst — dafür ein volles `docker compose up -d` bzw. scripts/smoke.sh nutzen.
#
# Usage: deploy/deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="${ROOT}/deploy"
PROFILE="prod"

cd "${COMPOSE_DIR}"

if [[ ! -f .env ]]; then
  echo "FEHLER: deploy/.env fehlt." >&2
  echo "        Lege sie aus der Vorlage an und fülle ALLE Secrets aus," >&2
  echo "        bevor du deployst:" >&2
  echo "          cp deploy/.env.example deploy/.env  &&  \$EDITOR deploy/.env" >&2
  echo "        (Platzhalterwerte führen zu Fail-fast-Abbruch der App-Container.)" >&2
  exit 1
fi

# ALTCHA-Sentinel-Adminkonsole nie mit Default-Credential starten: leeres oder
# "root"-Passwort ist ein bekannter Takeover-Vektor (auch wenn die Konsole nur im
# internen Netz hängt). Vor allem anderen abbrechen, damit der Operator einen
# eigenen Wert setzt. Wert direkt aus .env lesen, ohne die Datei zu sourcen.
altcha_pw="$(sed -n 's/^ALTCHA_ROOT_PASSWORD=//p' .env | head -n1)"
if [[ -z "${altcha_pw}" || "${altcha_pw}" == "root" ]]; then
  echo "FEHLER: ALTCHA_ROOT_PASSWORD in deploy/.env ist leer oder 'root'." >&2
  echo "        Setze ein eigenes, starkes Passwort, bevor du deployst." >&2
  exit 1
fi

# 1) Pull -------------------------------------------------------------------------------
old_head="$(git -C "${ROOT}" rev-parse --short HEAD)"
echo "==> git pull --ff-only (von ${old_head})"
git -C "${ROOT}" pull --ff-only
new_head="$(git -C "${ROOT}" rev-parse --short HEAD)"
if [[ "${old_head}" == "${new_head}" ]]; then
  echo "    Kein neuer Commit (${new_head}) — baue/prüfe trotzdem auf Image-Drift."
else
  echo "    ${old_head} -> ${new_head}"
fi

# 1b) Submodule synchronisieren (frontend/vendor/ui-kit = @stupa-makers/ui-kit) ---------
# Das web-Image baut das Angular-FE aus dem ausgecheckten Submodule-Stand; ohne Init/
# Update wäre frontend/vendor/ui-kit leer und `npm run build` (deploy/web/Dockerfile)
# bräche mit unaufgelöstem @stupa-makers/ui-kit-Pfad ab. `sync` zieht eine evtl. geänderte
# .gitmodules-URL nach, `update --init --recursive` checkt den gepinnten Commit aus.
echo "==> git submodule sync + update --init --recursive"
git -C "${ROOT}" submodule sync --recursive
git -C "${ROOT}" submodule update --init --recursive

# 2) Topologie + build-Service-Liste dynamisch aus compose lesen ------------------------
echo "==> docker compose config (Validierung)"
docker compose --profile "${PROFILE}" config -q

cfg="$(docker compose --profile "${PROFILE}" config --format json)"
project="$(jq -r '.name' <<<"${cfg}")"
read -r -a build_svcs <<<"$(jq -r '[.services|to_entries[]|select(.value.build)|.key]|join(" ")' <<<"${cfg}")"

# Image-Name eines build-Services: explizites image: aus der Config, sonst der von
# compose vergebene Default-Name <project>-<service>.
img_name() {
  local svc="$1" img
  img="$(jq -r --arg s "${svc}" '.services[$s].image // empty' <<<"${cfg}")"
  [[ -n "${img}" ]] && { printf '%s\n' "${img}"; return; }
  printf '%s-%s\n' "${project}" "${svc}"
}

img_id() {
  # Image-ID oder "none", falls das Image (noch) nicht existiert (z. B. Erstdeploy).
  # $(...) strippt den Stray-Newline, den `image inspect` bei fehlendem Image ausgibt.
  local id
  id="$(docker image inspect -f '{{.Id}}' "$1" 2>/dev/null)" || id=none
  printf '%s' "${id:-none}"
}

# 3) Image-IDs VOR dem Build merken -----------------------------------------------------
declare -A before
for svc in "${build_svcs[@]}"; do
  before["${svc}"]="$(img_id "$(img_name "${svc}")")"
done

# 4) Bauen ------------------------------------------------------------------------------
echo "==> docker compose build (${build_svcs[*]})"
docker compose --profile "${PROFILE}" build

# 5) Geänderte Services bestimmen (Image-ID gewechselt oder neu gebaut) -----------------
changed=()
for svc in "${build_svcs[@]}"; do
  after="$(img_id "$(img_name "${svc}")")"
  if [[ "${before[${svc}]}" != "${after}" ]]; then
    changed+=("${svc}")
  fi
done

if [[ "${#changed[@]}" -eq 0 ]]; then
  echo "==> Keine Image-Änderung — nichts neu zu starten."
  exit 0
fi

# 6) Nur geänderte Container neu erzeugen ----------------------------------------------
# `up -d <svcs>` ersetzt nur die genannten Services; laufende, unveränderte Services
# bleiben stehen. Abhängigkeiten (z. B. migrate vor api/worker) werden eingehalten —
# `alembic upgrade head` (idempotent) läuft vor dem App-Neustart. --no-build, da Schritt 4
# bereits gebaut hat.
echo "==> Neu starten: ${changed[*]}"
docker compose --profile "${PROFILE}" up -d --no-build "${changed[@]}"

echo "==> Fertig. Gebaut: ${build_svcs[*]} | Neu gestartet: ${changed[*]}"
