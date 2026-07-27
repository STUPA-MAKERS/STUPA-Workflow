"""HMAC-SHA256 signature and delivery headers.

`X-Signature` carries `sha256=<hex>`, an HMAC over `"{timestamp}.{body}"` with the
per-webhook `secret`. The `X-Timestamp` header holds unix seconds and is part of the
signature. An attacker can therefore not replay an intercepted body under a fresh
timestamp. This is the Stripe scheme.

The receiver checks that the timestamp is fresh. It then rebuilds the signature over
`"{X-Timestamp}.{body}"` and compares it in constant time. This module never logs the
`secret` and never exposes it.
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
    """Serialize the payload deterministically so bytes and signature stay stable."""
    return json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode("utf-8")


def signing_input(timestamp: int, body: bytes) -> bytes:
    """Build the signing input `"{timestamp}.{body}"` that binds the timestamp to the body."""
    return f"{timestamp}.".encode() + body


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    """Return `sha256=<hexdigest>` of the HMAC-SHA256 over `"{timestamp}.{body}"`."""
    digest = hmac.new(secret, signing_input(timestamp, body), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_headers(
    secret: bytes, body: bytes, *, event: str, timestamp: int
) -> dict[str, str]:
    """Build the delivery headers.

    They hold the signature over the timestamp and the body, the timestamp itself, the
    event name and the JSON content type.
    """
    return {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign(secret, timestamp, body),
        TIMESTAMP_HEADER: str(timestamp),
        EVENT_HEADER: event,
    }
