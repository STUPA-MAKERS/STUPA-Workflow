"""TDD: Auth-Kern-Typen (Principal/Applicant)."""

from __future__ import annotations

from app.modules.auth.principal import Applicant, Principal


def test_principal_has_permission() -> None:
    p = Principal(sub="u1", permissions={"admin.config"})
    assert p.has("admin.config")
    assert not p.has("vote.cast")


def test_admin_role_has_all_permissions() -> None:
    """#15: die admin-Rolle gewährt jedes Recht, auch ohne explizite Permission."""
    p = Principal(sub="root", roles=["admin"], permissions=set())
    assert p.has("admin.config")
    assert p.has("vote.cast")
    assert p.has("anything.at.all")


def test_non_admin_role_does_not_grant_extra() -> None:
    p = Principal(sub="u2", roles=["member"], permissions={"vote.cast"})
    assert p.has("vote.cast")
    assert not p.has("admin.config")


def test_principal_in_group() -> None:
    p = Principal(sub="u1", groups={"stupa"})
    assert p.in_group("stupa")
    assert not p.in_group("asta")


def test_principal_defaults_empty() -> None:
    p = Principal(sub="u1")
    assert p.roles == []
    assert p.permissions == set()
    assert p.groups == set()
    assert p.email is None


def test_applicant_edit_scope_covers_view() -> None:
    a = Applicant(application_id="app-1", scope="edit")
    assert a.allows("view")
    assert a.allows("edit")


def test_applicant_view_scope_is_view_only() -> None:
    a = Applicant(application_id="app-1", scope="view")
    assert a.allows("view")
    assert not a.allows("edit")
