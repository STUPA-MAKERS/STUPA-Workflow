"""The API runs in several processes (spec 002004).

The test reads the start command of the image: uvicorn starts ``API_WORKERS`` processes,
four when the variable is unset, and keeps the narrow proxy trust.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def _command() -> str:
    line = next(line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD "))
    return " ".join(json.loads(line.removeprefix("CMD ")))


def test_the_api_starts_four_workers_by_default() -> None:
    """Spec 002004: ``--workers`` reads ``API_WORKERS`` with the default 4."""
    command = _command()
    assert re.search(r'--workers "\$\{API_WORKERS:-4\}"', command), command
    assert "--proxy-headers" in command
    assert '--forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"' in command
