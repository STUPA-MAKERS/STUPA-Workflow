"""Logging-Setup (overview §5).

Einfache, strukturierte Konsolen-Logs inkl. Trace-Id (via Filter/Extra). Keine
Secrets/PII loggen. JSON-Logging/Aggregation später (Deployment).
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Root-Logger einmalig konfigurieren (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger().setLevel(level.upper())
        return
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _CONFIGURED = True
