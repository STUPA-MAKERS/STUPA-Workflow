"""Logging setup.

The application writes structured log lines to the console. Never log a secret or
personal data. The access log of uvicorn holds the path of each request, so a filter
masks the token of a path whose token is the only right of the request
(§NF/security/network/002817).
"""

from __future__ import annotations

import logging
import re

_configured = False

#: The paths whose segment after the prefix is a token: a push action and a calendar feed.
_TOKEN_PATH = re.compile(r"^(?:(/api/push/actions/)[^/?]+|(/api/calendar/)[^/?]+(\.ics))(?=$|\?)")

#: The fixed text that stands for a token in a log line.
TOKEN_MASK = "***"


def mask_token_path(path: str) -> str:
    """Return the path with the token of a push action or a calendar feed masked."""
    return _TOKEN_PATH.sub(
        lambda m: f"{m.group(1) or m.group(2)}{TOKEN_MASK}{m.group(3) or ''}", path
    )


class TokenPathFilter(logging.Filter):
    """Mask the token in the path of a uvicorn access log record.

    uvicorn passes ``(client, method, path, http_version, status)`` as the arguments
    of the record, so the filter rewrites the third one and keeps the line.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the path argument of an access record and keep the record."""
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], mask_token_path(args[2]), *args[3:])
        return True


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once (idempotent), with the token filter on access."""
    global _configured
    if _configured:
        logging.getLogger().setLevel(level.upper())
        return
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("uvicorn.access").addFilter(TokenPathFilter())
    _configured = True
