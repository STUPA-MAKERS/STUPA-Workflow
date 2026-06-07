"""HMAC-SHA256-Signatur + Versand-Header (security.md §5).

``X-Signature: sha256=<hex>`` über **``"{timestamp}.{body}"``** (HMAC mit dem pro-
Webhook-``secret``); der ``X-Timestamp`` (Unix-Sekunden) geht so **mit in die
Signatur** ein → ein Angreifer kann einen abgefangenen Body nicht mit frischem
Timestamp erneut einspielen (Replay-Schutz, Stripe-Schema). Der Empfänger prüft
Timestamp-Freshness **und** rekonstruiert die Signatur konstant-zeitig über
``"{X-Timestamp}.{body}"``. Das ``secret`` wird **nie** geloggt oder ausgegeben.
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


def signing_input(timestamp: int, body: bytes) -> bytes:
    """Signatur-Eingabe ``"{timestamp}.{body}"`` (bindet Timestamp an den Body)."""
    return f"{timestamp}.".encode() + body


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    """``sha256=<hexdigest>`` der HMAC-SHA256 von ``"{timestamp}.{body}"``."""
    digest = hmac.new(secret, signing_input(timestamp, body), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_headers(
    secret: bytes, body: bytes, *, event: str, timestamp: int
) -> dict[str, str]:
    """Versand-Header (Signatur über ts+Body, Timestamp, Event, JSON-Content-Type)."""
    return {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign(secret, timestamp, body),
        TIMESTAMP_HEADER: str(timestamp),
        EVENT_HEADER: event,
    }
