"""Secret-Verschlüsselung (Fernet, #fints): Roundtrip + Fehlerfälle."""

from __future__ import annotations

import pytest

from app.shared.crypto import SecretCryptoError, decrypt_secret, encrypt_secret

_KEY = "0123456789abcdef-fints-enc-key"


def test_roundtrip() -> None:
    token = encrypt_secret("1234", key=_KEY)
    assert token != "1234"
    assert decrypt_secret(token, key=_KEY) == "1234"


def test_wrong_key_raises() -> None:
    token = encrypt_secret("secret", key=_KEY)
    with pytest.raises(SecretCryptoError):
        decrypt_secret(token, key="a-totally-different-key-value")


def test_garbage_token_raises() -> None:
    with pytest.raises(SecretCryptoError):
        decrypt_secret("not-a-fernet-token", key=_KEY)


def test_unicode_pin() -> None:
    token = encrypt_secret("PÄsswörd-✓", key=_KEY)
    assert decrypt_secret(token, key=_KEY) == "PÄsswörd-✓"
