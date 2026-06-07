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
    signing_input,
)


def test_canonical_body_is_deterministic() -> None:
    a = canonical_body({"b": 1, "a": 2})
    b = canonical_body({"a": 2, "b": 1})
    assert a == b == b'{"a":2,"b":1}'


def test_sign_binds_timestamp_and_body() -> None:
    secret = b"s3cr3t-key-bytes"
    body = b'{"x":1}'
    expected = "sha256=" + hmac.new(
        secret, b"1700000000." + body, hashlib.sha256
    ).hexdigest()
    assert sign(secret, 1700000000, body) == expected
    assert signing_input(1700000000, body) == b"1700000000." + body


def test_signature_changes_with_timestamp() -> None:
    # Replay-Schutz: gleicher Body, neuer Timestamp → andere Signatur.
    secret, body = b"shared", canonical_body({"event": "status_changed"})
    assert sign(secret, 1000, body) != sign(secret, 2000, body)


def test_sign_verifiable_by_receiver() -> None:
    secret = b"shared"
    ts = 1700000000
    body = canonical_body({"event": "status_changed"})
    sig = sign(secret, ts, body)
    scheme, _, digest = sig.partition("=")
    assert scheme == "sha256"
    recomputed = hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(digest, recomputed)


def test_build_headers_shape() -> None:
    headers = build_headers(
        b"secret", b'{"x":1}', event="application_approved", timestamp=1700000000
    )
    assert headers["Content-Type"] == "application/json"
    assert headers[SIGNATURE_HEADER].startswith("sha256=")
    assert headers[TIMESTAMP_HEADER] == "1700000000"
    assert headers[EVENT_HEADER] == "application_approved"
    # Signatur bindet den gesendeten Timestamp.
    assert headers[SIGNATURE_HEADER] == sign(b"secret", 1700000000, b'{"x":1}')
