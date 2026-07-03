"""Magic-link token primitives — pure, no I/O.

Tokens are 32-byte CSPRNG values that only appear in the mail link; the DB
stores an HMAC-SHA256 digest peppered with `MAGIC_LINK_SECRET` (plaintext is
never persisted). Verification uses a constant-time compare.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_TOKEN_BYTES = 32


def generate_token() -> str:
    """Generate a URL-safe CSPRNG token (>=32 bytes of entropy)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str, pepper: str) -> bytes:
    """HMAC-SHA256(pepper, token) as a 32-byte digest (DB `token_hash`)."""
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).digest()


def verify_token_hash(token: str, pepper: str, expected: bytes) -> bool:
    """Constant-time compare of the freshly hashed token against the DB hash."""
    return hmac.compare_digest(hash_token(token, pepper), expected)
