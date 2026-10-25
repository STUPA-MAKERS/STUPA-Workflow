"""Logging setup.

The application writes structured log lines to the console. Never log a secret or
personal data.
"""

from __future__ import annotations

import logging

_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once (idempotent)."""
    global _configured
    if _configured:
        logging.getLogger().setLevel(level.upper())
        return
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _configured = True
