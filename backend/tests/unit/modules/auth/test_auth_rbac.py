"""TDD: RBAC resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.auth import rbac
from app.modules.auth.models import GroupMapping, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_assignment_valid_window() -> None:
    """Check the validity window: not yet valid, valid and expired."""
    assert rbac._assignment_valid(None, None, NOW) is True
    assert rbac._assignment_valid(NOW - timedelta(days=1), NOW + timedelta(days=1), NOW)
    assert rbac._assignment_valid(NOW + timedelta(days=1), None, NOW) is False
    assert rbac._assignment_valid(None, NOW - timedelta(days=1), NOW) is False


def test_assignment_valid_naive_db_values_do_not_crash() -> None:
    """Accept naive `valid_from` and `valid_until` values from the database.

    A naive timestamp carries no time zone. A comparison against the aware `now` raises a
    `TypeError` about offset-naive and offset-aware datetimes. That error would break the
    whole principal resolution: REST answers 500 and the WebSocket handshake answers 403.
    The rows are a naive expired window and a naive window that is not valid yet.
    """
    naive_from = (NOW - timedelta(days=1)).replace(tzinfo=None)
    naive_until = (NOW + timedelta(days=1)).replace(tzinfo=None)
    assert rbac._assignment_valid(naive_from, naive_until, NOW) is True
    assert rbac._assignment_valid(None, naive_from, NOW) is False
    assert rbac._assignment_valid(naive_until, None, NOW) is False


async def test_resolve_principal_with_naive_validity_window() -> None:
    """Resolve a principal with a naive validity window and no group mappings.

    The full resolver path for WebSocket and REST auth must survive it.
    """
    row = PrincipalRow(sub="u4", email=None, display_name=None, oidc_groups=None)
    naive_valid = RoleAssignment(
        role_id="r1",
        gremium_id="gid1",
        valid_from=(NOW - timedelta(days=1)).replace(tzinfo=None),
        valid_until=(NOW + timedelta(days=1)).replace(tzinfo=None),
    )
    db = fake_session(
        result(naive_valid),
        result(),
        result("vote.cast"),
        result("member"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"vote.cast"}
    assert p.groups == {"gid1"}


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
    """Put the OIDC group and the Gremium scope of the assignment in groups.

    A global group mapping has no Gremium scope.
    """
    row = PrincipalRow(sub="u2", email=None, display_name=None, oidc_groups=["grpA"])
    row.id = "pid"  # type: ignore[assignment]
    valid = RoleAssignment(role_id="r1", gremium_id="gid1", valid_from=None, valid_until=None)
    expired = RoleAssignment(
        role_id="rX", gremium_id=None, valid_from=None, valid_until=NOW - timedelta(days=1)
    )
    mapping_a = GroupMapping(oidc_group="grpA", role_id="r2")
    mapping_b = GroupMapping(oidc_group="grpA", role_id="r3")
    db = fake_session(
        result(valid, expired),
        result(mapping_a, mapping_b),
        result("application.read", "vote.cast"),
        result("member", "manager"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"application.read", "vote.cast"}
    assert set(p.roles) == {"member", "manager"}
    assert p.groups == {"grpA", "gid1"}


async def test_resolve_principal_assignment_without_gremium() -> None:
    """Resolve an assignment without Gremium scope and without OIDC groups."""
    row = PrincipalRow(sub="u3", email=None, display_name=None, oidc_groups=None)
    valid = RoleAssignment(role_id="r1", gremium_id=None, valid_from=None, valid_until=None)
    db = fake_session(
        result(valid),
        result("application.read"),
        result("member"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"application.read"}
    assert p.groups == set()
