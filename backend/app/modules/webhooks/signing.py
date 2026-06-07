"""HMAC-SHA256-Signatur + Versand-Header (security.md §5).

``X-Signature: sha256=<hex>`` über den **rohen Body** (HMAC mit dem pro-Webhook-
``secret``) plus ``X-Timestamp`` (Unix-Sekunden) als Replay-Fenster-Anker für den
Empfänger. Der Empfänger rekonstruiert die Signatur über den empfangenen Body und
vergleicht konstant-zeitig. Das ``secret`` wird **nie** geloggt oder ausgegeben.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
EVENT_HEADER = "X-Webhook-Event"


def canonical_body(payload: dict[str, Any]) -> bytes:
    """Payload deterministisch serialisieren (stabile Bytes → stabile Signatur)."""
    return json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode("utf-8")


def sign(secret: bytes, body: bytes) -> str:
    """``sha256=<hexdigest>`` der HMAC-SHA256 von ``body`` mit ``secret``."""
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_headers(
    secret: bytes, body: bytes, *, event: str, timestamp: int
) -> dict[str, str]:
    """Versand-Header (Signatur + Timestamp + Event + JSON-Content-Type)."""
    return {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign(secret, body),
        TIMESTAMP_HEADER: str(timestamp),
        EVENT_HEADER: event,
    }
