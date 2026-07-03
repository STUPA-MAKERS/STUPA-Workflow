"""HMAC-SHA256 signature + delivery headers.

``X-Signature: sha256=<hex>`` over ``"{timestamp}.{body}"`` (HMAC with the per-webhook
``secret``); the ``X-Timestamp`` (unix seconds) is part of the signature, so an attacker
cannot replay an intercepted body with a fresh timestamp (Stripe scheme). The receiver
checks timestamp freshness and reconstructs the signature in constant time over
``"{X-Timestamp}.{body}"``. The ``secret`` is never logged or exposed.
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
    """Serialize the payload deterministically (stable bytes -> stable signature)."""
    return json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode("utf-8")


def signing_input(timestamp: int, body: bytes) -> bytes:
    """Signing input ``"{timestamp}.{body}"`` (binds the timestamp to the body)."""
    return f"{timestamp}.".encode() + body


def sign(secret: bytes, timestamp: int, body: bytes) -> str:
    """``sha256=<hexdigest>`` of HMAC-SHA256 over ``"{timestamp}.{body}"``."""
    digest = hmac.new(secret, signing_input(timestamp, body), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_headers(
    secret: bytes, body: bytes, *, event: str, timestamp: int
) -> dict[str, str]:
    """Delivery headers (signature over ts+body, timestamp, event, JSON content type)."""
    return {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign(secret, timestamp, body),
        TIMESTAMP_HEADER: str(timestamp),
        EVENT_HEADER: event,
    }
