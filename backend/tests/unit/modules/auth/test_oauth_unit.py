"""Unit tests of the pure OAuth helpers and the scope cap in Principal (no database)."""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.modules.auth import oauth
from app.modules.auth.principal import Principal


def _challenge(verifier: str) -> str:
    d = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")


def test_parse_scope_default_and_dedup() -> None:
    """Parse an empty scope to the full default set, split into tokens, and dedup it."""
    assert oauth.parse_scope(None) == list(oauth.SCOPES.keys())
    assert oauth.parse_scope("   ") == list(oauth.SCOPES.keys())
    assert oauth.parse_scope("read read votes:write") == ["read", "votes:write"]


def test_parse_scope_rejects_unknown() -> None:
    with pytest.raises(oauth.OAuthError) as exc:
        oauth.parse_scope("read bogus:scope")
    assert exc.value.error == "invalid_scope"


def test_scope_permissions_union() -> None:
    """Unite the scope permissions; votes:write grants vote management, never a cast."""
    perms = oauth.scope_permissions(["read", "votes:write"])
    assert "application.read" in perms
    assert "vote.manage" in perms
    assert "vote.cast" not in perms
    assert "budget.manage" not in perms


def test_vote_cast_never_grantable() -> None:
    """Never grant `vote.cast`, also across the full default scope set.

    It is in no scope and is stripped even if a scope lists it.
    """
    from app.modules.auth.oauth import DEFAULT_SCOPE

    assert "vote.cast" in oauth.FORBIDDEN_PERMISSIONS
    all_perms = oauth.scope_permissions(oauth.parse_scope(DEFAULT_SCOPE))
    assert "vote.cast" not in all_perms
    assert all("vote.cast" not in p for p in oauth.SCOPES.values())


def test_verify_pkce_s256_roundtrip() -> None:
    verifier = "a" * 64
    assert oauth.verify_pkce_s256(verifier, _challenge(verifier)) is True
    assert oauth.verify_pkce_s256(verifier, _challenge("different")) is False


def test_token_prefixes_and_hash() -> None:
    """Check the token prefixes and store the SHA-256 digest, never the plaintext."""
    at = oauth.generate_access_token()
    rt = oauth.generate_refresh_token()
    assert oauth.is_access_token(at) and not oauth.is_access_token(rt)
    assert len(oauth.hash_token(at)) == 32
    assert oauth.hash_token(at) != oauth.hash_token(rt)


def test_unscoped_principal_unrestricted() -> None:
    """Apply the admin bypass in full for an unscoped principal."""
    p = Principal(sub="u", permissions={"application.read"})
    assert p.has("application.read") is True
    admin = Principal(sub="a", roles=["admin"])
    assert admin.has("budget.manage") is True


def test_scoped_principal_caps_permissions() -> None:
    """Cap a permission that the principal holds but the scope does not."""
    p = Principal(
        sub="u",
        permissions={"application.read", "budget.manage"},
        scope_permissions=frozenset({"application.read"}),
    )
    assert p.has("application.read") is True
    assert p.has("budget.manage") is False


def test_scope_caps_admin_bypass() -> None:
    """Keep the scope of an admin token; the admin bypass does not override it."""
    admin = Principal(
        sub="a",
        roles=["admin"],
        scope_permissions=frozenset({"application.read"}),
    )
    assert admin.has("application.read") is True
    assert admin.has("budget.manage") is False
    assert admin.has("admin.config") is False


def test_resolve_lifetime_known_and_default() -> None:
    """Resolve None or an unknown key to the default lifetime without a KeyError."""
    assert oauth.resolve_lifetime("30d") == 30 * 24 * 3600
    default = oauth.LIFETIMES[oauth.DEFAULT_LIFETIME]
    assert oauth.resolve_lifetime(None) == default
    assert oauth.resolve_lifetime("bogus") == default


def test_resolve_lifetime_never_and_bounded() -> None:
    """Resolve "never" to None, a token without expiry.

    Every finite lifetime is capped by MAX_LIFETIME_SECONDS.
    """
    assert oauth.LIFETIMES["never"] is None
    assert oauth.resolve_lifetime("never") is None
    assert oauth.MAX_LIFETIME_SECONDS == 90 * 24 * 3600
    for key, value in oauth.LIFETIMES.items():
        if value is None:
            continue
        ttl = oauth.resolve_lifetime(key)
        assert ttl is not None
        assert ttl <= oauth.MAX_LIFETIME_SECONDS


def test_resolve_lifetime_caps_oversized_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cap a catalog value that is too large at MAX_LIFETIME_SECONDS."""
    monkeypatch.setitem(oauth.LIFETIMES, "huge", oauth.MAX_LIFETIME_SECONDS * 10)
    assert oauth.resolve_lifetime("huge") == oauth.MAX_LIFETIME_SECONDS
