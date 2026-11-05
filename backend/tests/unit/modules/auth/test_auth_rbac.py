"""TDD: RBAC resolution."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.auth import rbac
from app.modules.auth.models import GroupMapping
from app.modules.auth.models import Principal as PrincipalRow
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


async def test_resolve_principal_no_roles() -> None:
    """Resolve a principal without assignments to no roles."""
    row = PrincipalRow(sub="u1", email="e@x.de", display_name="N", oidc_groups=None)
    db = fake_session(result())
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.sub == "u1"
    assert p.email == "e@x.de"
    assert p.permissions == set()
    assert p.roles == []
    assert p.groups == set()


async def test_resolve_principal_full_path() -> None:
    """Merge the assigned role and the roles of the OIDC group mappings.

    The assignment adds no group: only the OIDC group stays in groups.
    """
    row = PrincipalRow(sub="u2", email=None, display_name=None, oidc_groups=["grpA"])
    row.id = "pid"  # type: ignore[assignment]
    mapping_a = GroupMapping(oidc_group="grpA", role_id="r2")
    mapping_b = GroupMapping(oidc_group="grpA", role_id="r3")
    db = fake_session(
        result("r1"),
        result(mapping_a, mapping_b),
        result("application.read", "vote.cast"),
        result("member", "manager"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"application.read", "vote.cast"}
    assert set(p.roles) == {"member", "manager"}
    assert p.groups == {"grpA"}


async def test_resolve_principal_assignment_without_groups() -> None:
    """Resolve an assignment without OIDC groups."""
    row = PrincipalRow(sub="u3", email=None, display_name=None, oidc_groups=None)
    db = fake_session(
        result("r1"),
        result("application.read"),
        result("member"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"application.read"}
    assert p.groups == set()
