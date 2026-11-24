"""Sealed columns: a secret of an integration rests in the database only encrypted.

`Sealed` is the one column type that seals a value (§NF/security/integrity/002810). A module
declares a secret column as ``mapped_column(Sealed("<table>.<column>"))`` and reads and writes
the plain value, and only the database sees the sealed text. No module seals by itself.

Format: ``s1:<key id>:<base64url(nonce || ciphertext || tag)>``. ``s1`` is the version of the
format, and the key id is the first eight hex characters of the sha256 of the key. The cipher is
AES-256-GCM with a random 96-bit nonce, and the name of the column is the associated data, so a
sealed value that someone copies into another column does not open.

Keys: `SECRETS_KEY` seals and opens, and `SECRETS_KEY_OLD` (a list) only opens. The next write
of a value seals it with the current key, so a rotation needs no migration
(§NF/security/integrity/002811). Without a key and outside strict security, the key comes from
`SESSION_SECRET`, so a dev instance and the unit tests work without a new setting. Strict
security refuses to start without a key (`Settings`).

A value of an unknown key opens to an empty value and logs an error, and does not stop the read.
A copy of the production database on a dev instance then shows each secret as missing, and an
unchanged column is never written back, so the sealed value stays as it was.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.settings import decode_secrets_key, get_settings

_log = logging.getLogger(__name__)

#: The prefix of the current format.
PREFIX = "s1"
_NONCE_BYTES = 12
_KID_CHARS = 8


class SealError(ValueError):
    """A key or a sealed value is malformed, or a value does not open."""


def parse_key(text: str) -> bytes:
    """Decode a key from base64 (standard or URL-safe, padding optional).

    Raises:
        SealError: The text is not base64 of exactly 32 bytes.
    """
    try:
        return decode_secrets_key(text)
    except ValueError as exc:
        raise SealError(str(exc)) from exc


def key_id(key: bytes) -> str:
    """The id of a key: the first eight hex characters of its sha256."""
    return hashlib.sha256(key).hexdigest()[:_KID_CHARS]


def dev_key(session_secret: str) -> bytes:
    """The key outside strict security without `SECRETS_KEY`, derived from the session secret."""
    return hashlib.sha256(b"stupa-secrets-key\0" + session_secret.encode()).digest()


@dataclass(frozen=True)
class Keyring:
    """The current key and the keys that only open."""

    current: bytes
    older: tuple[bytes, ...] = ()

    def find(self, kid: str) -> bytes | None:
        """The key with this id, or None."""
        return next((k for k in (self.current, *self.older) if key_id(k) == kid), None)


@lru_cache(maxsize=4)
def _cached_keyring(secrets_key: str | None, old: tuple[str, ...], session_secret: str) -> Keyring:
    current = parse_key(secrets_key) if secrets_key else dev_key(session_secret)
    return Keyring(current, tuple(parse_key(k) for k in old))


def current_keyring() -> Keyring:
    """The keyring of the process settings."""
    s = get_settings()
    return _cached_keyring(s.secrets_key, tuple(s.secrets_key_old), s.session_secret)


def is_sealed(text: str) -> bool:
    """Whether a stored text has the sealed format."""
    return text.startswith(PREFIX + ":")


def seal(plain: bytes, purpose: str, ring: Keyring) -> str:
    """Seal bytes under the current key; `purpose` (the column) is the associated data."""
    nonce = os.urandom(_NONCE_BYTES)
    body = AESGCM(ring.current).encrypt(nonce, plain, purpose.encode())
    payload = base64.urlsafe_b64encode(nonce + body).decode().rstrip("=")
    return f"{PREFIX}:{key_id(ring.current)}:{payload}"


def open_sealed(text: str, purpose: str, ring: Keyring) -> bytes:
    """Open a sealed text.

    Raises:
        SealError: The text has no sealed format, its key is unknown, or it does not open.
    """
    parts = text.split(":")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise SealError("not a sealed value")
    key = ring.find(parts[1])
    if key is None:
        raise SealError(f"unknown key {parts[1]}")
    try:
        raw = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        return AESGCM(key).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], purpose.encode())
    except (binascii.Error, ValueError, InvalidTag) as exc:
        raise SealError("sealed value does not open") from exc


class Sealed(TypeDecorator[str]):
    """A text column that rests sealed: the code reads and writes the plain text."""

    impl = Text
    cache_ok = True

    def __init__(self, purpose: str) -> None:
        """Bind the column name, which is the associated data of each value."""
        super().__init__()
        self.purpose = purpose

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Seal a plain text before the write."""
        if value is None:
            return None
        return seal(value.encode(), self.purpose, current_keyring())

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Open a stored text after the read; an unknown key gives an empty text."""
        if value is None:
            return None
        opened = _open_or_empty(value, self.purpose)
        return opened.decode() if opened is not None else ""


class SealedBytes(TypeDecorator[bytes]):
    """A bytes column that rests sealed as text: the code reads and writes the plain bytes."""

    impl = Text
    cache_ok = True

    def __init__(self, purpose: str) -> None:
        """Bind the column name, which is the associated data of each value."""
        super().__init__()
        self.purpose = purpose

    def process_bind_param(self, value: bytes | None, dialect: Dialect) -> str | None:
        """Seal plain bytes before the write."""
        if value is None:
            return None
        return seal(value, self.purpose, current_keyring())

    def process_result_value(self, value: str | None, dialect: Dialect) -> bytes | None:
        """Open a stored text after the read; an unknown key gives empty bytes."""
        if value is None:
            return None
        opened = _open_or_empty(value, self.purpose)
        return opened if opened is not None else b""


def _open_or_empty(value: str, purpose: str) -> bytes | None:
    try:
        return open_sealed(value, purpose, current_keyring())
    except SealError as exc:
        _log.error("sealed column %s does not open: %s", purpose, exc)
        return None
