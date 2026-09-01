"""Pure OAuth2 helpers without database access: scope catalog, PKCE check, tokens.

A scope caps the rights of the logged-in principal. A scoped token gets exactly the
intersection of the RBAC permissions of the user and the permission set of the scope. See
`Principal.scope_permissions`. This also applies to an admin. The admin bypass in
`Principal.has` works only for in-scope permissions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Permissions that no agent gets, whatever the scope or the admin status says. To cast a
# ballot with `vote.cast` stays strictly human. Every scope resolution removes it.
# `backup.manage` joins it for the same reason: a backup holds the whole database in
# readable form, and a restore replaces it. Both stay with a human at a browser.
FORBIDDEN_PERMISSIONS: frozenset[str] = frozenset({"vote.cast", "backup.manage"})

# Scope key to the allowed permission keys. `read` covers every reading endpoint. The
# `*:write` scopes add the mutations. `votes:write` covers vote management only, that is
# create, open and close. It never covers `vote.cast`, because voting stays human.
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
    "budget:write": frozenset({"budget.structure", "budget.book"}),
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
            "admin.cd_variants",
            "admin.delegations",
            "admin.deadlines",
            "webhook.manage",
        }
    ),
}

# The full curated range that MCP requests by default. The server caps it to the rights of
# the logged-in user. A non-admin gets only their own subset.
DEFAULT_SCOPE = " ".join(SCOPES.keys())

# Hard cap in seconds for every token lifetime. No token lives forever. This value bounds
# even the longest selectable lifetime.
MAX_LIFETIME_SECONDS = 90 * 24 * 3600

# The selectable token lifetimes of the consent UI, mapped to the access-token TTL in
# seconds. The order is the display order. There is no "never" option on purpose. Every
# token expires after 90 days at the latest. The grants page can revoke a token at any
# time.
LIFETIMES: dict[str, int] = {
    "1h": 3600,
    "8h": 8 * 3600,
    "1d": 24 * 3600,
    "30d": 30 * 24 * 3600,
    "90d": 90 * 24 * 3600,
}
DEFAULT_LIFETIME = "30d"


def resolve_lifetime(key: str | None) -> int:
    """Map a lifetime key to an access TTL in seconds.

    An unknown key and `None` both fall back to the default. The result is always finite
    and capped by `MAX_LIFETIME_SECONDS`. The function never returns `None` for an
    unlimited lifetime.
    """
    if key is None or key not in LIFETIMES:
        key = DEFAULT_LIFETIME
    return min(LIFETIMES[key], MAX_LIFETIME_SECONDS)


# Display order of the scopes in the consent UI. The i18n keys live in the frontend.
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
    """OAuth2 protocol error, mapped to a 400 invalid_request or invalid_grant."""

    def __init__(self, error: str, description: str = "") -> None:
        super().__init__(description or error)
        self.error = error
        self.description = description


def parse_scope(raw: str | None) -> list[str]:
    """Parse a space-separated scope string into a validated list without duplicates.

    An empty string falls back to the default scope.

    Raises:
        OAuthError: A scope is unknown. The error code is `invalid_scope`.
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
    """Return the union of the permission sets of the scopes, minus the forbidden ones.

    The function subtracts `FORBIDDEN_PERMISSIONS`, so it always removes `vote.cast` and
    `backup.manage`. The removal holds even when a scope ever contains one of them, and it
    holds for an admin. The scope cap in `Principal.has` stops the admin bypass.
    """
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
    """Return the SHA-256 digest of a token.

    The database stores this digest. It never stores the plaintext token.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()


def tokens_match(token: str, expected_hash: bytes) -> bool:
    """Compare a token against its stored hash in constant time."""
    return hmac.compare_digest(hash_token(token), expected_hash)


def verify_pkce_s256(verifier: str, challenge: str) -> bool:
    """Check `base64url(sha256(verifier)) == challenge` in constant time (RFC 7636 S256)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)
