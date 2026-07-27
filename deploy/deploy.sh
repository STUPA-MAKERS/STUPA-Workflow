#!/usr/bin/env bash
# Production update: pull -> build -> restart only the changed containers.
#
# Steps:
#   1. Run git pull --ff-only in the repository root.
#   2. Build all build services. The layer cache makes an unchanged build almost free.
#   3. Compare the image ID of each build service before and after the build. Recreate
#      with `up -d` only the services with a new image ID. Unchanged services stay up,
#      and so do the data services postgres, redis, minio, clamav and altcha.
#
# Scope: --profile prod (backup included), as in deploy/README.md.
#
# Limit: the script detects a change through the image ID only. A change that touches
# only the compose config or the .env of an image-only service, such as a postgres env
# tweak, stays invisible here. In that case run a full `docker compose up -d`, or run
# scripts/smoke.sh.
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

# Never start the ALTCHA Sentinel admin console with a default credential. An empty
# password or the password "root" is a known takeover vector, even when the console sits
# on the internal network only. Abort before any other step, so the operator must set a
# strong password. Read the value straight from .env and do not source the file.
altcha_pw="$(sed -n 's/^ALTCHA_ROOT_PASSWORD=//p' .env | head -n1)"
if [[ -z "${altcha_pw}" || "${altcha_pw}" == "root" ]]; then
  echo "FEHLER: ALTCHA_ROOT_PASSWORD in deploy/.env ist leer oder 'root'." >&2
  echo "        Setze ein eigenes, starkes Passwort, bevor du deployst." >&2
  exit 1
fi

old_head="$(git -C "${ROOT}" rev-parse --short HEAD)"
echo "==> git pull --ff-only (von ${old_head})"
git -C "${ROOT}" pull --ff-only
new_head="$(git -C "${ROOT}" rev-parse --short HEAD)"
if [[ "${old_head}" == "${new_head}" ]]; then
  echo "    Kein neuer Commit (${new_head}) — baue/prüfe trotzdem auf Image-Drift."
else
  echo "    ${old_head} -> ${new_head}"
fi

# The web image builds the Angular frontend from the checked-out state of the submodule
# frontend/vendor/ui-kit (@stupa-makers/ui-kit). Without init and update that directory
# stays empty and `npm run build` (deploy/web/Dockerfile) aborts on an unresolved
# @stupa-makers/ui-kit path. `sync` picks up a changed .gitmodules URL.
# `update --init --recursive` checks out the pinned commit.
echo "==> git submodule sync + update --init --recursive"
git -C "${ROOT}" submodule sync --recursive
git -C "${ROOT}" submodule update --init --recursive

echo "==> docker compose config (Validierung)"
docker compose --profile "${PROFILE}" config -q

cfg="$(docker compose --profile "${PROFILE}" config --format json)"
project="$(jq -r '.name' <<<"${cfg}")"
read -r -a build_svcs <<<"$(jq -r '[.services|to_entries[]|select(.value.build)|.key]|join(" ")' <<<"${cfg}")"

# Image name of a build service: the explicit `image:` from the config, or else
# the default name <project>-<service> that compose assigns.
img_name() {
  local svc="$1" img
  img="$(jq -r --arg s "${svc}" '.services[$s].image // empty' <<<"${cfg}")"
  [[ -n "${img}" ]] && { printf '%s\n' "${img}"; return; }
  printf '%s-%s\n' "${project}" "${svc}"
}

img_id() {
  # Image ID, or "none" when the image does not exist yet, for example on a first deploy.
  # $(...) strips the stray newline that `image inspect` prints for a missing image.
  local id
  id="$(docker image inspect -f '{{.Id}}' "$1" 2>/dev/null)" || id=none
  printf '%s' "${id:-none}"
}

declare -A before
for svc in "${build_svcs[@]}"; do
  before["${svc}"]="$(img_id "$(img_name "${svc}")")"
done

echo "==> docker compose build (${build_svcs[*]})"
docker compose --profile "${PROFILE}" build

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

# `up -d <svcs>` replaces only the named services. Running, unchanged services stay up.
# compose keeps the dependencies, for example migrate before api and worker. The
# idempotent `alembic upgrade head` therefore runs before the app restarts. --no-build,
# because the build step above already built the images.
echo "==> Neu starten: ${changed[*]}"
docker compose --profile "${PROFILE}" up -d --no-build "${changed[@]}"

echo "==> Fertig. Gebaut: ${build_svcs[*]} | Neu gestartet: ${changed[*]}"
