"""The OAuth scope `paperless:use` (§F/integrations/mcp/002920), without a database."""

from __future__ import annotations

from app.modules.auth import oauth
from app.modules.auth.principal import Principal


def test_the_scope_carries_only_paperless_use() -> None:
    """The scope holds exactly `paperless.use`, the default asks for it, no admin key."""
    assert oauth.SCOPES["paperless:use"] == frozenset({"paperless.use"})
    assert oauth.scope_permissions(["paperless:use"]) == frozenset({"paperless.use"})
    assert "paperless:use" in oauth.DEFAULT_SCOPE.split()
    assert "paperless:use" in oauth.parse_scope(None)
    assert {"paperless:use"} == oauth.OPT_IN_SCOPES
    assert oauth.parse_scope("read paperless:use") == ["read", "paperless:use"]
    assert all("admin.paperless" not in perms for perms in oauth.SCOPES.values())
    assert "paperless:use" in oauth.SCOPE_ORDER
    admin = Principal(sub="a", roles=["admin"])
    capped = Principal(
        sub="a", roles=["admin"], scope_permissions=oauth.scope_permissions(["read"])
    )
    scoped = Principal(
        sub="a", roles=["admin"], scope_permissions=oauth.scope_permissions(["paperless:use"])
    )
    assert admin.has("paperless.use")
    assert not capped.has("paperless.use")
    assert scoped.has("paperless.use")
    assert not scoped.has("admin.paperless")


def test_the_consent_shows_the_scope_only_to_a_holder() -> None:
    """A requested `paperless:use` shows only when held; every other scope shows always."""
    requested = ["read", "paperless:use", "admin:write"]
    assert oauth.offered_scopes(requested, set()) == ["read", "admin:write"]
    assert oauth.offered_scopes(requested, {"paperless:use"}) == [
        "read",
        "paperless:use",
        "admin:write",
    ]
    assert oauth.offered_scopes(["read"], {"paperless:use"}) == ["read"]
