#!/bin/sh
# Copy the seed of the build-time cache into the mounted /cache volume. The seed holds
# the tectonic bundle and the LaTeX packages, see warmup.py. Copy missing entries only
# (-n), so an existing entry wins. The container then renders without internet access.
# Production needs that, because it blocks egress.
set -eu

if [ -d /cache-seed ]; then
  cp -Rn /cache-seed/. /cache/ 2>/dev/null || true
fi

exec uvicorn app:app --host 0.0.0.0 --port 8099
