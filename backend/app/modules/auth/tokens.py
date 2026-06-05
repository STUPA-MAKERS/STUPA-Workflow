"""Magic-Link-Token-Primitive (security.md §1) — rein, ohne I/O.

- `generate_token`: 32-Byte-CSPRNG (`secrets.token_urlsafe`), nur im Mail-Link.
- `hash_token`: HMAC-SHA256 mit `MAGIC_LINK_SECRET` als Pepper → `bytea` für die DB
  (Klartext-Token wird **nie** gespeichert).
- `verify_token_hash`: konstantzeitiger Vergleich (`hmac.compare_digest`).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_TOKEN_BYTES = 32


def generate_token() -> str:
    """URL-sicherer CSPRNG-Token (≥32 Byte Entropie)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str, pepper: str) -> bytes:
    """HMAC-SHA256(pepper, token) → 32-Byte-Digest (DB-`token_hash`)."""
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).digest()


def verify_token_hash(token: str, pepper: str, expected: bytes) -> bool:
    """Konstantzeitiger Vergleich des frisch gehashten Tokens gegen den DB-Hash."""
    return hmac.compare_digest(hash_token(token, pepper), expected)
