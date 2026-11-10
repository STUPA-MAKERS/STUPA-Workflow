"""TDD: the core auth types Principal and Applicant."""

from __future__ import annotations

from app.modules.auth.principal import Applicant, Principal


def test_principal_has_permission() -> None:
    p = Principal(sub="u1", permissions={"admin.config"})
    assert p.has("admin.config")
    assert not p.has("vote.cast")


def test_admin_role_has_all_permissions() -> None:
    """The admin role grants every permission, even without an explicit grant."""
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


def test_applicant_binds_one_application() -> None:
    a = Applicant(application_id="app-1")
    assert a.application_id == "app-1"


def test_applicant_covers_its_application_or_its_address_list() -> None:
    """A link session covers its one application, an e-mail session its list."""
    link = Applicant(application_id="a1")
    assert link.covers("a1")
    assert not link.covers("a2")
    assert link.identity == "a1"
    mail = Applicant(email="lena@example.org", application_ids=frozenset({"a2", "a3"}))
    assert mail.covers("a3")
    assert not mail.covers("a1")
    assert mail.identity == "email:lena@example.org"
