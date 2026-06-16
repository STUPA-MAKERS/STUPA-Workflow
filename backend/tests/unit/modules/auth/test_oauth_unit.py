"""Unit-Tests der reinen OAuth-Helfer + der Scope-Kappung im Principal (DB-frei)."""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.modules.auth import oauth
from app.modules.auth.principal import Principal


def _challenge(verifier: str) -> str:
    d = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")


# --------------------------------------------------------------------- scopes
def test_parse_scope_default_and_dedup() -> None:
    # Empty → the full default scope set (split into tokens, not one blob).
    assert oauth.parse_scope(None) == list(oauth.SCOPES.keys())
    assert oauth.parse_scope("   ") == list(oauth.SCOPES.keys())
    assert oauth.parse_scope("read read votes:write") == ["read", "votes:write"]


def test_parse_scope_rejects_unknown() -> None:
    with pytest.raises(oauth.OAuthError) as exc:
        oauth.parse_scope("read bogus:scope")
    assert exc.value.error == "invalid_scope"


def test_scope_permissions_union() -> None:
    perms = oauth.scope_permissions(["read", "votes:write"])
    assert "application.read" in perms
    # votes:write grants vote MANAGEMENT only — never ballot-casting.
    assert "vote.manage" in perms
    assert "vote.cast" not in perms
    assert "budget.manage" not in perms


def test_vote_cast_never_grantable() -> None:
    # `vote.cast` is hard-forbidden: not in any scope, and stripped even if a scope
    # listed it. Holds across the full default scope set too.
    from app.modules.auth.oauth import DEFAULT_SCOPE

    assert "vote.cast" in oauth.FORBIDDEN_PERMISSIONS
    all_perms = oauth.scope_permissions(oauth.parse_scope(DEFAULT_SCOPE))
    assert "vote.cast" not in all_perms
    assert all("vote.cast" not in p for p in oauth.SCOPES.values())


# ----------------------------------------------------------------------- PKCE
def test_verify_pkce_s256_roundtrip() -> None:
    verifier = "a" * 64
    assert oauth.verify_pkce_s256(verifier, _challenge(verifier)) is True
    assert oauth.verify_pkce_s256(verifier, _challenge("different")) is False


# ---------------------------------------------------------------- token shape
def test_token_prefixes_and_hash() -> None:
    at = oauth.generate_access_token()
    rt = oauth.generate_refresh_token()
    assert oauth.is_access_token(at) and not oauth.is_access_token(rt)
    assert oauth.tokens_match(at, oauth.hash_token(at))
    assert not oauth.tokens_match(at, oauth.hash_token(rt))


# -------------------------------------------------- Principal scope-Kappung
def test_unscoped_principal_unrestricted() -> None:
    p = Principal(sub="u", permissions={"application.read"})
    assert p.has("application.read") is True
    # ungescoped: Admin-Bypass voll wirksam
    admin = Principal(sub="a", roles=["admin"])
    assert admin.has("budget.manage") is True


def test_scoped_principal_caps_permissions() -> None:
    p = Principal(
        sub="u",
        permissions={"application.read", "budget.manage"},
        scope_permissions=frozenset({"application.read"}),
    )
    assert p.has("application.read") is True
    # im Besitz, aber NICHT im Scope → gekappt
    assert p.has("budget.manage") is False


def test_scope_caps_admin_bypass() -> None:
    # Scoped Token eines Admins: der Admin-Bypass darf den Scope NICHT aushebeln.
    admin = Principal(
        sub="a",
        roles=["admin"],
        scope_permissions=frozenset({"application.read"}),
    )
    assert admin.has("application.read") is True
    assert admin.has("budget.manage") is False
    assert admin.has("admin.config") is False


# ------------------------------------------------------------------- lifetimes
def test_resolve_lifetime_known_default_and_never() -> None:
    assert oauth.resolve_lifetime("30d") == 30 * 24 * 3600
    assert oauth.resolve_lifetime("never") is None
    # None oder unbekannt → Default-Lebensdauer (fail-safe, kein KeyError).
    default = oauth.LIFETIMES[oauth.DEFAULT_LIFETIME]
    assert oauth.resolve_lifetime(None) == default
    assert oauth.resolve_lifetime("bogus") == default
