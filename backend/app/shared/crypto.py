"""Symmetrische Verschlüsselung sensibler At-Rest-Werte (Fernet).

Hält Online-Banking-PINs (#fints) **verschlüsselt** in der DB. Der Fernet-Schlüssel
wird aus dem konfigurierten ``fints_enc_key``-Secret abgeleitet (``sha256`` →
url-safe-base64), damit jede ausreichend lange Passphrase funktioniert — Fernet selbst
verlangt einen exakten 32-Byte-base64-Schlüssel. ``cryptography`` ist bereits transitive
Abhängigkeit (``pyjwt[crypto]``) und wird hier **lazy** importiert (der reine Contract-CI-
Pfad lädt es nie). Klartext-PIN/Secret werden **nie** geloggt (security.md §10).
"""

from __future__ import annotations

import base64
import hashlib


class SecretCryptoError(RuntimeError):
    """Ver-/Entschlüsselung fehlgeschlagen (ungültiger Token oder Schlüssel)."""


def _fernet(key_material: str):  # type: ignore[no-untyped-def]  # noqa: ANN202 (Fernet aus lazy import)
    """Fernet-Instanz aus beliebigem Secret (über sha256 auf 32 Byte normalisiert)."""
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str, *, key: str) -> str:
    """Klartext mit dem abgeleiteten Schlüssel verschlüsseln → ASCII-Token (Fernet)."""
    return _fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, *, key: str) -> str:
    """Fernet-Token mit dem abgeleiteten Schlüssel entschlüsseln → Klartext.

    :raises SecretCryptoError: Token/Schlüssel passt nicht (z. B. nach Key-Rotation)."""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise SecretCryptoError("could not decrypt stored secret") from exc
