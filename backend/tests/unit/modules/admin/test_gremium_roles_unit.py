"""Unit tests without a DB: OIDC group mappings of a gremium and the membership sync.

The memberships come from the OIDC groups only. The tests cover the mapping CRUD of
`GremiumRoleService` and the pure branches of `membership_sync`: add, change, remove,
the tie-break between two roles in one gremium, and the audit entry per change.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.modules.admin import gremium_roles, membership_sync
from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import GremiumGroupMapping, GremiumMembership, GremiumRole
from app.modules.admin.schemas import GremiumGroupMappingCreate, GremiumGroupMappingUpdate
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.errors import ConflictError, NotFoundError
from tests._support.auth_fakes import fake_session, result


def _role(gremium_id: UUID | None = None, key: str = "member", perms=None) -> GremiumRole:
    r = GremiumRole(
        gremium_id=gremium_id or uuid4(),
        key=key,
        name_i18n={},
        permissions=["vote.cast"] if perms is None else perms,
    )
    r.id = uuid4()
    return r


def _mapping(gremium_id: UUID, role_id: UUID, group: str = "stupa") -> GremiumGroupMapping:
    m = GremiumGroupMapping(gremium_id=gremium_id, gremium_role_id=role_id, oidc_group=group)
    m.id = uuid4()
    return m


def _membership(pid: UUID, gid: UUID, role_id: UUID) -> GremiumMembership:
    m = GremiumMembership(principal_id=pid, gremium_id=gid, gremium_role_id=role_id)
    m.id = uuid4()
    return m


def _principal(groups: list[str] | None) -> PrincipalRow:
    row = PrincipalRow(sub="sub-1", oidc_groups=groups)
    row.id = uuid4()
    return row


def _ids_on_flush(db: Any) -> None:
    """Give every added object an id, because the fake ``flush`` sets no primary key."""

    async def _flush() -> None:
        for o in db.added:
            if getattr(o, "id", None) is None:
                o.id = uuid4()
        db.flushed += 1

    db.flush = _flush


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the audit entries of the sync and the service without the hash chain."""
    seen: list[dict[str, Any]] = []

    class _Audit:
        def __init__(self, _session: Any) -> None:
            pass

        async def record(self, **kw: Any) -> None:
            seen.append(kw)

    monkeypatch.setattr(membership_sync, "AuditService", _Audit)
    monkeypatch.setattr(gremium_roles, "AuditService", _Audit)
    return seen


@pytest.fixture
def synced(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace the full sync in the service with a recorder."""
    calls: list[Any] = []

    async def _sync_all(session: Any) -> int:
        calls.append(session)
        return 0

    monkeypatch.setattr(gremium_roles, "sync_all_memberships", _sync_all)
    return calls


# ---------------------------------------------------------------- schema


def test_mapping_create_refuses_reserved_vote_prefix() -> None:
    with pytest.raises(ValidationError):
        GremiumGroupMappingCreate(oidcGroup="vote:abc", gremiumRoleId=uuid4())


def test_mapping_update_refuses_reserved_vote_prefix() -> None:
    with pytest.raises(ValidationError):
        GremiumGroupMappingUpdate(oidcGroup="vote:abc")


def test_mapping_update_needs_a_field() -> None:
    with pytest.raises(ValidationError):
        GremiumGroupMappingUpdate()


def test_mapping_update_accepts_role_only() -> None:
    payload = GremiumGroupMappingUpdate(gremiumRoleId=uuid4())
    assert payload.oidc_group is None


# ---------------------------------------------------------------- mapping CRUD


async def test_list_group_mappings() -> None:
    gid = uuid4()
    m = _mapping(gid, uuid4())
    out = await GremiumRoleService(fake_session(result(m))).list_group_mappings(gid)
    assert [o.oidc_group for o in out] == ["stupa"]
    assert out[0].gremium_id == gid


async def test_create_mapping_role_not_found() -> None:
    svc = GremiumRoleService(fake_session(gets=[None]))
    payload = GremiumGroupMappingCreate(oidcGroup="stupa", gremiumRoleId=uuid4())
    with pytest.raises(NotFoundError, match="gremium role"):
        await svc.create_group_mapping(uuid4(), payload, "admin")


async def test_create_mapping_role_of_other_gremium() -> None:
    role = _role()
    svc = GremiumRoleService(fake_session(gets=[role]))
    payload = GremiumGroupMappingCreate(oidcGroup="stupa", gremiumRoleId=role.id)
    with pytest.raises(ConflictError, match="does not belong"):
        await svc.create_group_mapping(uuid4(), payload, "admin")


async def test_create_mapping_audits_syncs_and_commits(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    gid = uuid4()
    role = _role(gid)
    db = fake_session(gets=[role])
    _ids_on_flush(db)
    payload = GremiumGroupMappingCreate(oidcGroup="stupa", gremiumRoleId=role.id)
    out = await GremiumRoleService(db).create_group_mapping(gid, payload, "admin")
    assert out.oidc_group == "stupa" and out.gremium_role_id == role.id
    assert audits[0]["target_type"] == "gremium_group_mapping"
    assert audits[0]["target_id"] == str(out.id)
    assert synced == [db]
    assert db.committed == 1


async def test_create_mapping_duplicate_group_409(synced: list[Any]) -> None:
    gid = uuid4()
    role = _role(gid)
    db = fake_session(gets=[role])
    rollbacks: list[int] = []

    async def _flush() -> None:
        raise IntegrityError("INSERT", {}, Exception("uq_gremium_group_mapping"))

    async def _rollback() -> None:
        rollbacks.append(1)

    db.flush = _flush
    db.rollback = _rollback
    payload = GremiumGroupMappingCreate(oidcGroup="stupa", gremiumRoleId=role.id)
    with pytest.raises(ConflictError, match="already maps"):
        await GremiumRoleService(db).create_group_mapping(gid, payload, "admin")
    assert rollbacks == [1]
    assert synced == []


async def test_update_mapping_not_found() -> None:
    svc = GremiumRoleService(fake_session(gets=[None]))
    with pytest.raises(NotFoundError):
        await svc.update_group_mapping(
            uuid4(), GremiumGroupMappingUpdate(oidcGroup="x"), "admin"
        )


async def test_update_mapping_role_of_other_gremium() -> None:
    gid = uuid4()
    row = _mapping(gid, uuid4())
    svc = GremiumRoleService(fake_session(gets=[row, _role()]))
    with pytest.raises(ConflictError, match="does not belong"):
        await svc.update_group_mapping(
            row.id, GremiumGroupMappingUpdate(gremiumRoleId=uuid4()), "admin"
        )


async def test_update_mapping_changes_role_and_group(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    gid = uuid4()
    row = _mapping(gid, uuid4())
    new_role = _role(gid, key="vorstand")
    db = fake_session(gets=[row, new_role])
    out = await GremiumRoleService(db).update_group_mapping(
        row.id,
        GremiumGroupMappingUpdate(oidcGroup="stupa-board", gremiumRoleId=new_role.id),
        "admin",
    )
    assert out.oidc_group == "stupa-board"
    assert out.gremium_role_id == new_role.id
    assert len(audits) == 1 and synced == [db] and db.committed == 1


async def test_update_mapping_group_only_keeps_role(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    role_id = uuid4()
    row = _mapping(uuid4(), role_id)
    db = fake_session(gets=[row])
    out = await GremiumRoleService(db).update_group_mapping(
        row.id, GremiumGroupMappingUpdate(oidcGroup="other"), "admin"
    )
    assert out.gremium_role_id == role_id and out.oidc_group == "other"


async def test_delete_mapping_not_found() -> None:
    svc = GremiumRoleService(fake_session(gets=[None]))
    with pytest.raises(NotFoundError):
        await svc.delete_group_mapping(uuid4(), "admin")


async def test_delete_mapping_syncs(audits: list[dict[str, Any]], synced: list[Any]) -> None:
    row = _mapping(uuid4(), uuid4())
    db = fake_session(gets=[row])
    await GremiumRoleService(db).delete_group_mapping(row.id, "admin")
    assert row in db.deleted
    assert audits[0]["target_id"] == str(row.id)
    assert synced == [db] and db.committed == 1


async def test_delete_role_in_use_by_mapping_blocked() -> None:
    role = _role(key="custom")
    db = fake_session(result(), result(uuid4()), gets=[role])  # no membership, a mapping
    with pytest.raises(ConflictError, match="group mapping"):
        await GremiumRoleService(db).delete_role(role.id, "admin")


# ---------------------------------------------------------------- sync


async def test_sync_without_groups_removes_all(audits: list[dict[str, Any]]) -> None:
    row = _principal(None)
    old = _membership(row.id, uuid4(), uuid4())
    db = fake_session(result(old))  # no mapping query: the group set is empty
    assert await membership_sync.sync_principal_memberships(db, row) is True
    assert db.deleted == [old]
    assert [a["target_id"] for a in audits] == [str(old.id)]
    assert audits[0]["actor"] == membership_sync.SYNC_ACTOR
    assert db.committed == 0


async def test_sync_adds_membership_from_mapping(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa"])
    gid = uuid4()
    role = _role(gid)
    db = fake_session(result((gid, role)), result())
    _ids_on_flush(db)
    assert await membership_sync.sync_principal_memberships(db, row) is True
    [added] = db.added
    assert (added.principal_id, added.gremium_id, added.gremium_role_id) == (
        row.id,
        gid,
        role.id,
    )
    assert len(audits) == 1


async def test_sync_no_change_is_a_noop(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa"])
    gid = uuid4()
    role = _role(gid)
    current = _membership(row.id, gid, role.id)
    db = fake_session(result((gid, role)), result(current))
    assert await membership_sync.sync_principal_memberships(db, row) is False
    assert db.added == [] and db.deleted == [] and audits == []
    assert db.flushed == 0


async def test_sync_changes_role_in_place(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa-board"])
    gid = uuid4()
    board = _role(gid, key="vorstand", perms=["vote.cast", "vote.manage"])
    current = _membership(row.id, gid, uuid4())
    db = fake_session(result((gid, board)), result(current))
    assert await membership_sync.sync_principal_memberships(db, row) is True
    assert current.gremium_role_id == board.id
    assert db.added == [] and db.deleted == []
    assert [a["target_id"] for a in audits] == [str(current.id)]


async def test_sync_drops_duplicate_row_of_one_gremium(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa"])
    gid = uuid4()
    role = _role(gid)
    first = _membership(row.id, gid, role.id)
    second = _membership(row.id, gid, role.id)
    db = fake_session(result((gid, role)), result(first, second))
    assert await membership_sync.sync_principal_memberships(db, row) is True
    assert db.deleted == [second]


async def test_sync_prefers_role_with_more_permissions(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa", "stupa-board"])
    gid = uuid4()
    member = _role(gid, key="member", perms=["vote.cast"])
    board = _role(gid, key="vorstand", perms=["vote.cast", "session.manage"])
    db = fake_session(result((gid, member), (gid, board)), result())
    _ids_on_flush(db)
    await membership_sync.sync_principal_memberships(db, row)
    assert db.added[0].gremium_role_id == board.id


async def test_sync_tie_breaks_on_lower_key(audits: list[dict[str, Any]]) -> None:
    row = _principal(["a", "b"])
    gid = uuid4()
    manager = _role(gid, key="manager", perms=["vote.cast"])
    alpha = _role(gid, key="alpha", perms=["vote.manage"])
    db = fake_session(result((gid, manager), (gid, alpha)), result())
    _ids_on_flush(db)
    await membership_sync.sync_principal_memberships(db, row)
    assert db.added[0].gremium_role_id == alpha.id


async def test_sync_all_counts_changed_principals(audits: list[dict[str, Any]]) -> None:
    changed = _principal(None)
    unchanged = _principal(None)
    db = fake_session(
        result(changed, unchanged),  # all principals
        result(_membership(changed.id, uuid4(), uuid4())),  # changed: one stale row
        result(),  # unchanged: no row
    )
    assert await membership_sync.sync_all_memberships(db) == 1
