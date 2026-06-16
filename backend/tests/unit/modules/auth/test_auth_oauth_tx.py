"""Unit: signierter OAuth-AS-Transaktions-Cookie (``issue``/``load_oauth_tx``).

Reine itsdangerous-Signatur-Logik (DB-frei) — deckt Roundtrip, kaputte Signatur,
falsches Secret und fehlende/Nicht-Dict-Payloads ab.
"""

from __future__ import annotations

from app.modules.auth.sessions import (
    _OAUTH_TX_SALT,
    _serializer,
    issue_oauth_tx,
    load_oauth_tx,
)

_SECRET = "x" * 32
_DATA = {
    "client_id": "mcp",
    "redirect_uri": "http://127.0.0.1:7777/cb",
    "code_challenge": "abc123",
    "scope": "read votes:write",
    "state": "s1",
}


def test_oauth_tx_roundtrip() -> None:
    out = load_oauth_tx(_SECRET, issue_oauth_tx(_SECRET, _DATA), 600)
    assert out is not None
    assert out["client_id"] == "mcp"
    assert out["redirect_uri"] == "http://127.0.0.1:7777/cb"
    assert out["scope"] == "read votes:write"
    assert out["state"] == "s1"


def test_oauth_tx_defaults_missing_optional_fields() -> None:
    tx = issue_oauth_tx(
        _SECRET, {"client_id": "c", "redirect_uri": "r", "code_challenge": "ch"}
    )
    out = load_oauth_tx(_SECRET, tx, 600)
    assert out is not None
    assert out["state"] == "" and out["scope"] == ""


def test_oauth_tx_bad_signature_returns_none() -> None:
    assert load_oauth_tx(_SECRET, "not-a-valid-token", 600) is None


def test_oauth_tx_wrong_secret_returns_none() -> None:
    tx = issue_oauth_tx("a" * 32, _DATA)
    assert load_oauth_tx("b" * 32, tx, 600) is None


def test_oauth_tx_missing_required_fields_returns_none() -> None:
    # Signiert, aber ohne Pflichtfelder (redirect_uri/code_challenge) → abgelehnt.
    blob = _serializer(_SECRET, _OAUTH_TX_SALT).dumps({"client_id": "c"})
    assert load_oauth_tx(_SECRET, blob, 600) is None


def test_oauth_tx_non_dict_payload_returns_none() -> None:
    blob = _serializer(_SECRET, _OAUTH_TX_SALT).dumps(["not", "a", "dict"])
    assert load_oauth_tx(_SECRET, blob, 600) is None
