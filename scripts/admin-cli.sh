#!/usr/bin/env bash
# Launch the antragsplattform admin REPL (./admin-cli).
#
# On the first run the script creates a dedicated venv. It rebuilds the venv when
# pyproject.toml changes. It then starts the installed console script with the correct
# interpreter.
#
# Usage. Run this from the repo root, or from anywhere with the postgres port forwarded:
#   ./scripts/admin-cli.sh                # full-screen command REPL
#   ./scripts/admin-cli.sh --read-only    # writes disabled
#   ./scripts/admin-cli.sh --check        # test the DB connection only
#
# The script finds the DB access in this order:
#   1. $DATABASE_URL, if it is set.
#   2. The DSN from deploy/.env, rewritten to localhost and the host port that the
#      compose file publishes. 127.0.0.1:5433:5432 gives 5433. This also works through
#      `ssh -L 5433:127.0.0.1:5433 <vm>`.
#   3. `docker compose exec postgres psql`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_DIR="$REPO_ROOT/admin-cli"
VENV="$CLI_DIR/.venv"
PYTHON="${PYTHON:-python3}"
MARKER="$VENV/.installed"

need_install=0
[[ -x "$VENV/bin/antragsplattform-admin" ]] || need_install=1
[[ -f "$MARKER" && ! "$CLI_DIR/pyproject.toml" -nt "$MARKER" ]] || need_install=1

if [[ "$need_install" -eq 1 ]]; then
    if [[ ! -d "$VENV" ]]; then
        echo "==> creating venv: $VENV" >&2
        "$PYTHON" -m venv "$VENV"
    fi
    echo "==> installing admin-cli into venv" >&2
    "$VENV/bin/python" -m pip install --quiet --upgrade pip >&2
    "$VENV/bin/python" -m pip install --quiet -e "$CLI_DIR" >&2
    touch "$MARKER"
fi

# Run from the repo root, so deploy/docker-compose.yml (the default COMPOSE_FILE) resolves.
cd "$REPO_ROOT"
exec "$VENV/bin/antragsplattform-admin" "$@"
