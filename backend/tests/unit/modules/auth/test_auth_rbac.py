"""TDD: RBAC-Auflösung (security.md §2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.auth import rbac
from app.modules.auth.models import GroupMapping, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_assignment_valid_window() -> None:
    assert rbac._assignment_valid(None, None, NOW) is True
    assert rbac._assignment_valid(NOW - timedelta(days=1), NOW + timedelta(days=1), NOW)
    assert rbac._assignment_valid(NOW + timedelta(days=1), None, NOW) is False  # noch nicht
    assert rbac._assignment_valid(None, NOW - timedelta(days=1), NOW) is False  # abgelaufen


def test_assignment_valid_naive_db_values_do_not_crash() -> None:
    """Regression: naive ``valid_from``/``valid_until`` (timestamp ohne tz) aus der DB.

    Vor dem Fix warf der Vergleich mit dem aware ``now``
    ``TypeError: can't compare offset-naive and offset-aware datetimes`` und legte
    damit die komplette Principal-Auflösung lahm (REST 500, WS-Handshake-403).
    """
    naive_from = (NOW - timedelta(days=1)).replace(tzinfo=None)
    naive_until = (NOW + timedelta(days=1)).replace(tzinfo=None)
    assert rbac._assignment_valid(naive_from, naive_until, NOW) is True
    assert rbac._assignment_valid(None, naive_from, NOW) is False  # naiv, abgelaufen
    assert rbac._assignment_valid(naive_until, None, NOW) is False  # naiv, noch nicht


async def test_resolve_principal_with_naive_validity_window() -> None:
    """Voller Resolver-Pfad mit naivem Gültigkeitsfenster crasht nicht (WS/REST-Auth)."""
    row = PrincipalRow(sub="u4", email=None, display_name=None, oidc_groups=None)
    naive_valid = RoleAssignment(
        role_id="r1",
        gremium_id="gid1",
        valid_from=(NOW - timedelta(days=1)).replace(tzinfo=None),
        valid_until=(NOW + timedelta(days=1)).replace(tzinfo=None),
    )
    db = fake_session(
        result(naive_valid),
        result(),  # keine GroupMappings
        result("vote.cast"),
        result("member"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"vote.cast"}
    assert p.groups == {"gid1"}


async def test_resolve_principal_no_roles() -> None:
    row = PrincipalRow(sub="u1", email="e@x.de", display_name="N", oidc_groups=None)
    db = fake_session(result())  # keine Assignments
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.sub == "u1"
    assert p.email == "e@x.de"
    assert p.permissions == set()
    assert p.roles == []
    assert p.groups == set()


async def test_resolve_principal_full_path() -> None:
    row = PrincipalRow(sub="u2", email=None, display_name=None, oidc_groups=["grpA"])
    row.id = "pid"  # type: ignore[assignment]
    valid = RoleAssignment(role_id="r1", gremium_id="gid1", valid_from=None, valid_until=None)
    expired = RoleAssignment(
        role_id="rX", gremium_id=None, valid_from=None, valid_until=NOW - timedelta(days=1)
    )
    mapping_global = GroupMapping(oidc_group="grpA", role_id="r2", gremium_id=None)
    mapping_scoped = GroupMapping(oidc_group="grpA", role_id="r3", gremium_id="gid2")
    db = fake_session(
        result(valid, expired),
        result(mapping_global, mapping_scoped),
        result("application.read", "vote.cast"),
        result("member", "manager"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"application.read", "vote.cast"}
    assert set(p.roles) == {"member", "manager"}
    # OIDC-Gruppe + beide Gremium-Scopes (Assignment + Mapping) landen in groups.
    assert p.groups == {"grpA", "gid1", "gid2"}


async def test_resolve_principal_assignment_without_gremium() -> None:
    row = PrincipalRow(sub="u3", email=None, display_name=None, oidc_groups=None)
    valid = RoleAssignment(role_id="r1", gremium_id=None, valid_from=None, valid_until=None)
    db = fake_session(
        result(valid),
        result("application.read"),
        result("member"),
    )
    p = await rbac.resolve_principal(db, row, NOW)
    assert p.permissions == {"application.read"}
    assert p.groups == set()  # kein Gremium-Scope, keine OIDC-Gruppen
