"""Pure OAuth2 helpers (DB-free): scope catalog, PKCE check, token generation/hashing.

Scopes cap the logged-in principal's rights: a scoped token gets exactly the
intersection of the user's RBAC permissions and the scope's permission set
(``Principal.scope_permissions``). This applies to admins too — the admin
bypass in ``Principal.has`` only works for in-scope permissions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Permissions NEVER granted to an agent, regardless of scope or admin status.
# `vote.cast` (casting a ballot) is strictly human: hard-removed from every
# scope resolution.
FORBIDDEN_PERMISSIONS: frozenset[str] = frozenset({"vote.cast"})

# Scope key -> allowed permission keys. `read` covers all reading endpoints; the
# `*:write` scopes add mutations. `votes:write` covers vote MANAGEMENT only
# (create/open/close), never `vote.cast` — voting itself stays human.
SCOPES: dict[str, frozenset[str]] = {
    "read": frozenset(
        {
            "application.read",
            "application.export",
            "budget.view",
            "budget.export",
            "audit.read",
            "audit.verify",
        }
    ),
    "applications:write": frozenset(
        {"application.create", "application.transition", "application.manage"}
    ),
    "votes:write": frozenset({"vote.manage"}),
    "budget:write": frozenset({"budget.structure", "budget.book", "account.manage"}),
    "meetings:write": frozenset({"meeting.manage", "protocol.finalize"}),
    "forms:write": frozenset({"form.configure"}),
    "flows:write": frozenset({"flow.configure"}),
    "admin:write": frozenset(
        {
            "admin.site",
            "admin.gremien",
            "admin.types",
            "admin.roles",
            "admin.users",
            "admin.group_mappings",
            "admin.gremium_roles",
            "admin.delegations",
            "admin.deadlines",
            "webhook.manage",
        }
    ),
}

# Full curated range (MCP default request). Capped server-side to the logged-in
# user's rights — a non-admin gets only their subset.
DEFAULT_SCOPE = " ".join(SCOPES.keys())

# Hard cap for every token lifetime (seconds). There are NO never-expiring
# tokens: even the longest selectable value is bounded by this.
MAX_LIFETIME_SECONDS = 90 * 24 * 3600  # 90 days

# Selectable token lifetimes (consent UI) -> access-token TTL in seconds; order
# = display order. Deliberately no "never" option — every token expires (<=90d)
# regardless of the always-available revocation via the grants page.
LIFETIMES: dict[str, int] = {
    "1h": 3600,
    "8h": 8 * 3600,
    "1d": 24 * 3600,
    "30d": 30 * 24 * 3600,
    "90d": 90 * 24 * 3600,
}
DEFAULT_LIFETIME = "30d"


def resolve_lifetime(key: str | None) -> int:
    """Map a lifetime key to an access TTL in seconds (unknown/``None`` -> default).

    The result is always finite and capped by ``MAX_LIFETIME_SECONDS`` — it can
    never return ``None`` (unlimited)."""
    if key is None or key not in LIFETIMES:
        key = DEFAULT_LIFETIME
    return min(LIFETIMES[key], MAX_LIFETIME_SECONDS)


# Display order of scopes in the consent UI (i18n keys live in the frontend).
SCOPE_ORDER: tuple[str, ...] = (
    "read",
    "applications:write",
    "votes:write",
    "meetings:write",
    "budget:write",
    "forms:write",
    "flows:write",
    "admin:write",
)

_ACCESS_PREFIX = "apat_"  # antragsplattform access token
_REFRESH_PREFIX = "aprt_"  # antragsplattform refresh token
_TOKEN_BYTES = 32


class OAuthError(ValueError):
    """OAuth2 protocol error (mapped to 400 invalid_request/invalid_grant)."""

    def __init__(self, error: str, description: str = "") -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description


def parse_scope(raw: str | None) -> list[str]:
    """Parse a space-separated scope string into a validated, deduplicated list.

    Unknown scopes raise ``OAuthError('invalid_scope')``; empty falls back to
    the default scope.
    """
    if not raw or not raw.strip():
        raw = DEFAULT_SCOPE
    out: list[str] = []
    for tok in raw.split():
        if tok not in SCOPES:
            raise OAuthError("invalid_scope", f"unknown scope: {tok}")
        if tok not in out:
            out.append(tok)
    return out


def scope_permissions(scopes: list[str]) -> frozenset[str]:
    """Union of all scopes' permission sets, minus FORBIDDEN_PERMISSIONS.

    `vote.cast` is hard-removed here — even if a scope ever contained it or the
    user is admin (the scope cap in ``Principal.has`` neutralizes the bypass)."""
    perms: set[str] = set()
    for s in scopes:
        perms |= SCOPES.get(s, frozenset())
    return frozenset(perms - FORBIDDEN_PERMISSIONS)


def is_access_token(token: str) -> bool:
    return token.startswith(_ACCESS_PREFIX)


def generate_access_token() -> str:
    return _ACCESS_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def generate_refresh_token() -> str:
    return _REFRESH_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """SHA-256 digest of a token (for DB storage; plaintext never persisted)."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def tokens_match(token: str, expected_hash: bytes) -> bool:
    """Constant-time compare of a token against its stored hash."""
    return hmac.compare_digest(hash_token(token), expected_hash)


def verify_pkce_s256(verifier: str, challenge: str) -> bool:
    """RFC 7636 S256: ``base64url(sha256(verifier)) == challenge`` (constant-time)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)
