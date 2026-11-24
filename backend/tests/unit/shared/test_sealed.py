"""Unit: sealing and opening of the secrets (§NF/security/integrity/002810, 002811)."""

from __future__ import annotations

import base64
import logging
import os

import pytest
from sqlalchemy.dialects import postgresql

from app.settings import load_settings
from app.shared import sealed
from app.shared.sealed import (
    Keyring,
    Sealed,
    SealedBytes,
    SealError,
    dev_key,
    is_sealed,
    key_id,
    open_sealed,
    parse_key,
    seal,
)

_DIALECT = postgresql.dialect()


def _key() -> bytes:
    return os.urandom(32)


def test_a_sealed_value_opens_and_hides_the_plain_text() -> None:
    ring = Keyring(_key())
    text = seal(b"geheim", "t.c", ring)
    assert is_sealed(text)
    assert "geheim" not in text
    assert text.split(":")[1] == key_id(ring.current)
    assert open_sealed(text, "t.c", ring) == b"geheim"


def test_two_seals_of_one_value_differ() -> None:
    ring = Keyring(_key())
    assert seal(b"x", "t.c", ring) != seal(b"x", "t.c", ring)


def test_a_value_does_not_open_in_another_column() -> None:
    ring = Keyring(_key())
    with pytest.raises(SealError, match="does not open"):
        open_sealed(seal(b"x", "t.a", ring), "t.b", ring)


def test_an_old_key_still_opens() -> None:
    old = _key()
    text = seal(b"alt", "t.c", Keyring(old))
    assert open_sealed(text, "t.c", Keyring(_key(), (old,))) == b"alt"


@pytest.mark.parametrize(
    ("text", "reason"),
    [("plain", "not a sealed"), ("s1:00000000:AAAA", "unknown key"), ("s2:a:b", "not a sealed")],
)
def test_a_bad_value_does_not_open(text: str, reason: str) -> None:
    with pytest.raises(SealError, match=reason):
        open_sealed(text, "t.c", Keyring(_key()))


def test_a_broken_payload_does_not_open() -> None:
    ring = Keyring(_key())
    with pytest.raises(SealError, match="does not open"):
        open_sealed(f"s1:{key_id(ring.current)}:AAAA", "t.c", ring)


def test_parse_key_takes_standard_and_url_safe_base64() -> None:
    raw = bytes(range(250, 256)) * 5 + b"ab"
    assert parse_key(base64.b64encode(raw).decode()) == raw
    assert parse_key(base64.urlsafe_b64encode(raw).decode().rstrip("=")) == raw


@pytest.mark.parametrize("text", ["!!!", base64.b64encode(b"short").decode()])
def test_parse_key_refuses_a_bad_key(text: str) -> None:
    with pytest.raises(SealError):
        parse_key(text)


def test_the_column_types_seal_and_open() -> None:
    column = Sealed("t.c")
    stored = column.process_bind_param("geheim", _DIALECT)
    assert stored is not None and is_sealed(stored)
    assert column.process_result_value(stored, _DIALECT) == "geheim"
    assert column.process_bind_param(None, _DIALECT) is None
    assert column.process_result_value(None, _DIALECT) is None

    binary = SealedBytes("t.b")
    stored_bytes = binary.process_bind_param(b"\x00\x01", _DIALECT)
    assert stored_bytes is not None and is_sealed(stored_bytes)
    assert binary.process_result_value(stored_bytes, _DIALECT) == b"\x00\x01"
    assert binary.process_bind_param(None, _DIALECT) is None
    assert binary.process_result_value(None, _DIALECT) is None


def test_a_value_of_an_unknown_key_reads_as_empty(caplog: pytest.LogCaptureFixture) -> None:
    foreign = Keyring(_key())
    with caplog.at_level(logging.ERROR, logger="app.shared.sealed"):
        assert Sealed("t.c").process_result_value(seal(b"x", "t.c", foreign), _DIALECT) == ""
        assert SealedBytes("t.c").process_result_value(seal(b"x", "t.c", foreign), _DIALECT) == b""
    assert "unknown key" in caplog.text


def test_the_keyring_follows_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    current = base64.b64encode(_key()).decode()
    old = base64.b64encode(_key()).decode()
    monkeypatch.setattr(
        sealed,
        "get_settings",
        lambda: load_settings(secrets_key=current, secrets_key_old=[old]),
    )
    ring = sealed.current_keyring()
    assert ring.current == parse_key(current)
    assert ring.older == (parse_key(old),)


def test_without_a_key_outside_strict_security_the_session_secret_gives_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sealed,
        "get_settings",
        lambda: load_settings(secrets_key=None, strict_security=False, session_secret="s" * 16),
    )
    assert sealed.current_keyring().current == dev_key("s" * 16)
