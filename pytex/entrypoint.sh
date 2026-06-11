#!/bin/sh
# Seed des Build-Zeit-Caches (tectonic-Bundle + LaTeX-Pakete, s. warmup.py) in das
# gemountete /cache-Volume kopieren — nur fehlende Einträge (-n), Bestand gewinnt.
# Damit rendert der Container auch OHNE Internet (Egress-Sperre in Produktion).
set -eu

if [ -d /cache-seed ]; then
  cp -Rn /cache-seed/. /cache/ 2>/dev/null || true
fi

exec uvicorn app:app --host 0.0.0.0 --port 8099
