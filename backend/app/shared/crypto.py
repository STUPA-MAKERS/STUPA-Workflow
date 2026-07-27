"""Symmetric encryption of sensitive at-rest values (Fernet).

This module keeps the online-banking PINs encrypted in the database. It derives the
Fernet key from the configured ``fints_enc_key`` secret (``sha256`` -> url-safe base64),
because Fernet needs an exact 32-byte base64 key.

Important: ``sha256`` is not a password KDF. It has no salt and no work factor.
``fints_enc_key`` MUST therefore be a random, high-entropy secret, for example
``Fernet.generate_key()`` or 32 random bytes. An attacker can brute-force a human-chosen
passphrase offline after a database leak. ``_MIN_SECRET_LEN`` checks the length only,
not the entropy.

``cryptography`` is already a transitive dependency, and this module imports it lazily.
The module never logs a plaintext PIN or secret.
"""

from __future__ import annotations

import base64
import hashlib


class SecretCryptoError(RuntimeError):
    """Encryption/decryption failed (invalid token or key)."""


def _fernet(key_material: str):  # type: ignore[no-untyped-def]  # noqa: ANN202  (Fernet from lazy import)
    """Build a Fernet instance from any secret (normalized to 32 bytes with sha256)."""
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, *, key: str) -> str:
    """Encrypt plaintext with the derived key and return an ASCII Fernet token."""
    return _fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, *, key: str) -> str:
    """Decrypt a Fernet token with the derived key and return the plaintext.

    Raises:
        SecretCryptoError: The token and the key do not match, for example after a key
            rotation.
    """
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise SecretCryptoError("could not decrypt stored secret") from exc
