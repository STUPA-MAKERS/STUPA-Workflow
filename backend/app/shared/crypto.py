"""Symmetrische Verschlüsselung sensibler At-Rest-Werte (Fernet).

Hält Online-Banking-PINs (#fints) **verschlüsselt** in der DB. Der Fernet-Schlüssel
wird aus dem konfigurierten ``fints_enc_key``-Secret abgeleitet (``sha256`` →
url-safe-base64), weil Fernet einen exakten 32-Byte-base64-Schlüssel verlangt.

**Wichtig (#fints-review):** ``sha256`` ist *kein* Passwort-KDF (kein Salt, kein
Work-Factor). ``fints_enc_key`` MUSS daher ein **zufälliges, hochentropisches** Secret sein
(z. B. ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key())"``
oder 32 Zufallsbytes) — eine vom Menschen gewählte Passphrase wäre bei DB-Leak offline
brute-forcebar. ``_MIN_SECRET_LEN`` prüft nur die Länge, nicht die Entropie.

``cryptography`` ist bereits transitive Abhängigkeit (``pyjwt[crypto]``) und wird hier
**lazy** importiert (der reine Contract-CI-Pfad lädt es nie). Klartext-PIN/Secret werden
**nie** geloggt (security.md §10).
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
