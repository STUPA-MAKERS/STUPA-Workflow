#!/usr/bin/env bash
# Launch the antragsplattform admin TUI (./admin-cli).
#
# Creates/updates a dedicated venv on first run (or when pyproject.toml changes) and starts the
# installed console script with the right interpreter. Runs from the repo root so the default
# relative compose file (deploy/docker-compose.yml) resolves.
#
# Usage (from the repo root, on the host that runs the stack):
#   ./scripts/admin-cli.sh                # full-screen TUI
#   ./scripts/admin-cli.sh --read-only    # writes disabled
#   ./scripts/admin-cli.sh --check        # just test DB connectivity
#
# DB access: set DATABASE_URL for a direct connection; otherwise the running stack is reached via
# `docker compose -f $COMPOSE_FILE exec postgres psql` (same model as remove-admin-role.sh).
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

# Run from repo root so deploy/docker-compose.yml (default COMPOSE_FILE) resolves.
cd "$REPO_ROOT"
exec "$VENV/bin/antragsplattform-admin" "$@"
