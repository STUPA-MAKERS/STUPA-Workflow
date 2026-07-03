"""Symmetric encryption of sensitive at-rest values (Fernet).

Keeps online-banking PINs encrypted in the DB. The Fernet key is derived from the
configured ``fints_enc_key`` secret (``sha256`` -> url-safe base64), because Fernet
requires an exact 32-byte base64 key.

Important: ``sha256`` is not a password KDF (no salt, no work factor), so
``fints_enc_key`` MUST be a random, high-entropy secret (e.g. ``Fernet.generate_key()``
or 32 random bytes); a human-chosen passphrase would be offline-bruteforceable on a DB
leak. ``_MIN_SECRET_LEN`` checks length only, not entropy.

``cryptography`` is already a transitive dependency and is imported lazily. Plaintext
PIN/secret are never logged.
"""

from __future__ import annotations

import base64
import hashlib


class SecretCryptoError(RuntimeError):
    """Encryption/decryption failed (invalid token or key)."""


def _fernet(key_material: str):  # type: ignore[no-untyped-def]  # noqa: ANN202  (Fernet from lazy import)
    """Fernet instance from any secret (normalized to 32 bytes via sha256)."""
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, *, key: str) -> str:
    """Encrypt plaintext with the derived key -> ASCII token (Fernet)."""
    return _fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, *, key: str) -> str:
    """Decrypt a Fernet token with the derived key -> plaintext.

    Raises:
        SecretCryptoError: token/key mismatch (e.g. after key rotation)."""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise SecretCryptoError("could not decrypt stored secret") from exc
