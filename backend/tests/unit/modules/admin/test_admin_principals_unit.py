"""Unit tests without a DB: RBAC service paths, principal search, revoke, permission catalog.

These tests run on ``fake_session`` with its ``scalars`` and ``get`` queues. They prove the
mapper and the assignment join that avoids an N+1 query. They also prove the empty-path
branch of the search and the 404 and success branches of the revoke.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.modules.admin.service import ConfigService
from app.modules.admin.service.rbac import _principal_out
from app.modules.auth.models import Principal, Role, RoleAssignment
from app.shared.errors import ConflictError, NotFoundError
from app.shared.permissions import PERMISSION_CATALOGUE
from tests._support.auth_fakes import fake_session, result


def _principal(pid: UUID, sub: str, email: str | None = None) -> Principal:
    row = Principal(sub=sub, email=email, display_name="Max", oidc_groups=None)
    row.id = pid
    row.last_login = None
    return row


def _assignment(pid: UUID) -> RoleAssignment:
    a = RoleAssignment(
        principal_id=pid,
        role_id=uuid4(),
        gremium_id=None,
        granted_by="admin",
        valid_from=None,
        valid_until=None,
        delegate_voting=False,
    )
    a.id = uuid4()
    return a


async def test_search_principals_joins_assignments() -> None:
    pid1, pid2 = uuid4(), uuid4()
    p1, p2 = _principal(pid1, "sub-1", "a@x.de"), _principal(pid2, "sub-2")
    db = fake_session(
        result(p1, p2),  # matched principals
        result(_assignment(pid1)),  # only pid1 has an assignment
    )
    out = await ConfigService(db).search_principals("ma")
    assert [p.sub for p in out] == ["sub-1", "sub-2"]
    assert len(out[0].assignments) == 1
    assert out[1].assignments == []


async def test_search_principals_empty_skips_assignment_query() -> None:
    db = fake_session(result())  # no principals → no second query
    assert await ConfigService(db).search_principals(None) == []


def test_principal_out_maps_last_login_iso() -> None:
    from datetime import UTC, datetime

    row = _principal(uuid4(), "sub-9")
    row.last_login = datetime(2026, 6, 7, 9, 0, tzinfo=UTC)
    out = _principal_out(row, [])
    assert out.last_login == "2026-06-07T09:00:00+00:00"


def test_list_permissions_includes_seeded_keys() -> None:
    perms = ConfigService(fake_session()).list_permissions()
    assert perms == list(PERMISSION_CATALOGUE)
    assert "flow.configure" in perms
    assert "admin.roles" in perms


async def test_delete_role_assignment_not_found() -> None:
    db = fake_session(gets=[None])  # session.get → None
    with pytest.raises(NotFoundError):
        await ConfigService(db).delete_role_assignment(
            "00000000-0000-0000-0000-0000000000ff", "admin"  # type: ignore[arg-type]
        )


async def test_delete_role_assignment_ok() -> None:
    row = _assignment(uuid4())
    # gets: the assignment. results: the audit advisory lock and the prev-hash lookup.
    db = fake_session(result(), result(), gets=[row])
    await ConfigService(db).delete_role_assignment(row.id, "admin")
    assert db.deleted == [row]
    assert db.committed == 1


def _admin_role() -> Role:
    r = Role(key="admin", name_i18n={"de": "Administrator"})
    r.id = uuid4()
    return r


def _member_role() -> Role:
    r = Role(key="member", name_i18n={"de": "Mitglied"})
    r.id = uuid4()
    return r


async def test_delete_role_assignment_blocks_member_removal() -> None:
    """#61: nobody can revoke the global member role."""
    row = _assignment(uuid4())  # gremium_id=None
    # gets: assignment, guard role (member, not admin, so it returns early), member-check role.
    db = fake_session(gets=[row, _member_role(), _member_role()])
    with pytest.raises(ConflictError):
        await ConfigService(db).delete_role_assignment(row.id, "actor")
    assert db.deleted == []


async def test_delete_role_assignment_blocks_self_admin_removal() -> None:
    """#40: an admin must not revoke the own admin role."""
    pid = uuid4()
    row = _assignment(pid)
    # gets: assignment → admin role → own principal (sub == actor)
    db = fake_session(gets=[row, _admin_role(), _principal(pid, "me-sub")])
    with pytest.raises(ConflictError):
        await ConfigService(db).delete_role_assignment(row.id, "me-sub")
    assert db.deleted == []


async def test_set_principal_active_blocks_self_deactivation() -> None:
    """#44: an account must not deactivate itself."""
    pid = uuid4()
    db = fake_session(gets=[_principal(pid, "me-sub")])
    with pytest.raises(ConflictError):
        await ConfigService(db).set_principal_active(pid, False, "me-sub")


async def test_set_principal_active_allows_self_reactivation() -> None:
    """An account may reactivate itself. The guard blocks only the deactivation."""
    pid = uuid4()
    # gets: the principal. results: the audit lock, the audit hash, the assignments query.
    db = fake_session(result(), result(), result(), gets=[_principal(pid, "me-sub")])
    out = await ConfigService(db).set_principal_active(pid, True, "me-sub")
    assert out.active is True


async def test_delete_role_assignment_allows_admin_of_other_principal() -> None:
    """An actor may revoke the admin role of another principal.

    The guard blocks only the self-lockout case.
    """
    pid = uuid4()
    row = _assignment(pid)
    db = fake_session(
        result(),
        result(),
        gets=[row, _admin_role(), _principal(pid, "someone-else")],
    )
    await ConfigService(db).delete_role_assignment(row.id, "me-sub")
    assert db.deleted == [row]
