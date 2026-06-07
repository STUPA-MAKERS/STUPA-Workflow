"""HMAC-Signatur + Header (T-19, security.md §5)."""

from __future__ import annotations

import hashlib
import hmac

from app.modules.webhooks.signing import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    build_headers,
    canonical_body,
    sign,
)


def test_canonical_body_is_deterministic() -> None:
    a = canonical_body({"b": 1, "a": 2})
    b = canonical_body({"a": 2, "b": 1})
    assert a == b == b'{"a":2,"b":1}'


def test_sign_matches_hmac_sha256() -> None:
    secret = b"s3cr3t-key-bytes"
    body = b'{"x":1}'
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    assert sign(secret, body) == expected


def test_sign_verifiable_by_receiver() -> None:
    secret = b"shared"
    body = canonical_body({"event": "status_changed"})
    sig = sign(secret, body)
    scheme, _, digest = sig.partition("=")
    assert scheme == "sha256"
    recomputed = hmac.new(secret, body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(digest, recomputed)


def test_build_headers_shape() -> None:
    headers = build_headers(
        b"secret", b'{"x":1}', event="application_approved", timestamp=1700000000
    )
    assert headers["Content-Type"] == "application/json"
    assert headers[SIGNATURE_HEADER].startswith("sha256=")
    assert headers[TIMESTAMP_HEADER] == "1700000000"
    assert headers[EVENT_HEADER] == "application_approved"
