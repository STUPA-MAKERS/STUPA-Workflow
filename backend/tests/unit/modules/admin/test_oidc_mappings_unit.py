"""Unit tests without a DB: the gremium OIDC mappings and the membership sync.

An OIDC group links in separate ways: to the membership in a gremium, and to a role in
a gremium. The tests cover the mapping CRUD of `OidcMappingService` and the branches of
`membership_sync`: membership only with a membership mapping, the default role
`member`, a role mapping that applies only to members, the tie-break between two roles,
and the audit entry per change.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.modules.admin import membership_sync, oidc_mappings
from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import (
    Gremium,
    GremiumMembership,
    GremiumMembershipMapping,
    GremiumRole,
    GremiumRoleMapping,
)
from app.modules.admin.oidc_mappings import OidcMappingService
from app.modules.admin.schemas import (
    GremiumMembershipMappingCreate,
    GremiumMembershipMappingUpdate,
    GremiumRoleMappingCreate,
    GremiumRoleMappingUpdate,
    GroupMappingCreate,
)
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


def _gremium() -> Gremium:
    g = Gremium(name="StuPa", slug="stupa")
    g.id = uuid4()
    return g


def _membership_mapping(gremium_id: UUID, group: str = "stupa") -> GremiumMembershipMapping:
    m = GremiumMembershipMapping(gremium_id=gremium_id, oidc_group=group)
    m.id = uuid4()
    return m


def _role_mapping(role_id: UUID, group: str = "stupa-board") -> GremiumRoleMapping:
    m = GremiumRoleMapping(gremium_role_id=role_id, oidc_group=group)
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
    monkeypatch.setattr(oidc_mappings, "AuditService", _Audit)
    return seen


@pytest.fixture
def synced(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace the full sync in the service with a recorder."""
    calls: list[Any] = []

    async def _sync_all(session: Any) -> int:
        calls.append(session)
        return 0

    monkeypatch.setattr(oidc_mappings, "sync_all_memberships", _sync_all)
    return calls


def _raise_on_flush(db: Any) -> list[int]:
    rollbacks: list[int] = []

    async def _flush() -> None:
        raise IntegrityError("INSERT", {}, Exception("unique"))

    async def _rollback() -> None:
        rollbacks.append(1)

    db.flush = _flush
    db.rollback = _rollback
    return rollbacks


# ---------------------------------------------------------------- schema


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (GremiumMembershipMappingCreate, {"oidcGroup": "vote:x", "gremiumId": str(uuid4())}),
        (GremiumMembershipMappingUpdate, {"oidcGroup": "vote:x"}),
        (GremiumRoleMappingCreate, {"oidcGroup": "vote:x", "gremiumRoleId": str(uuid4())}),
        (GremiumRoleMappingUpdate, {"oidcGroup": "vote:x"}),
        (GroupMappingCreate, {"oidcGroup": "vote:x", "roleId": str(uuid4())}),
    ],
)
def test_reserved_vote_prefix_is_refused(model: Any, body: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(body)


@pytest.mark.parametrize("model", [GremiumMembershipMappingUpdate, GremiumRoleMappingUpdate])
def test_update_needs_a_field(model: Any) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({})


def test_global_mapping_has_no_gremium() -> None:
    payload = GroupMappingCreate.model_validate(
        {"oidcGroup": "fsr", "roleId": str(uuid4()), "gremiumId": str(uuid4())}
    )
    assert "gremium_id" not in type(payload).model_fields


# ---------------------------------------------------------------- membership mappings


async def test_list_membership_mappings() -> None:
    gid = uuid4()
    out = await OidcMappingService(
        fake_session(result(_membership_mapping(gid)))
    ).list_membership_mappings()
    assert [(o.gremium_id, o.oidc_group) for o in out] == [(gid, "stupa")]


async def test_create_membership_mapping_unknown_gremium() -> None:
    svc = OidcMappingService(fake_session(gets=[None]))
    payload = GremiumMembershipMappingCreate(oidcGroup="stupa", gremiumId=uuid4())
    with pytest.raises(NotFoundError, match="gremium"):
        await svc.create_membership_mapping(payload, "admin")


async def test_create_membership_mapping_audits_syncs_commits(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    g = _gremium()
    db = fake_session(gets=[g])
    _ids_on_flush(db)
    payload = GremiumMembershipMappingCreate(oidcGroup="stupa", gremiumId=g.id)
    out = await OidcMappingService(db).create_membership_mapping(payload, "admin")
    assert out.gremium_id == g.id and out.oidc_group == "stupa"
    assert audits[0]["target_type"] == "gremium_membership_mapping"
    assert audits[0]["target_id"] == str(out.id)
    assert synced == [db] and db.committed == 1


async def test_create_membership_mapping_duplicate_409(synced: list[Any]) -> None:
    g = _gremium()
    db = fake_session(gets=[g])
    rollbacks = _raise_on_flush(db)
    payload = GremiumMembershipMappingCreate(oidcGroup="stupa", gremiumId=g.id)
    with pytest.raises(ConflictError, match="already maps"):
        await OidcMappingService(db).create_membership_mapping(payload, "admin")
    assert rollbacks == [1] and synced == []


async def test_update_membership_mapping_not_found() -> None:
    svc = OidcMappingService(fake_session(gets=[None]))
    with pytest.raises(NotFoundError):
        await svc.update_membership_mapping(
            uuid4(), GremiumMembershipMappingUpdate(oidcGroup="x"), "admin"
        )


async def test_update_membership_mapping_unknown_gremium() -> None:
    row = _membership_mapping(uuid4())
    svc = OidcMappingService(fake_session(gets=[row, None]))
    with pytest.raises(NotFoundError, match="gremium"):
        await svc.update_membership_mapping(
            row.id, GremiumMembershipMappingUpdate(gremiumId=uuid4()), "admin"
        )


async def test_update_membership_mapping_changes_both(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    row = _membership_mapping(uuid4())
    g = _gremium()
    db = fake_session(gets=[row, g])
    out = await OidcMappingService(db).update_membership_mapping(
        row.id, GremiumMembershipMappingUpdate(oidcGroup="asta", gremiumId=g.id), "admin"
    )
    assert (out.gremium_id, out.oidc_group) == (g.id, "asta")
    assert synced == [db] and db.committed == 1


async def test_update_membership_mapping_group_only(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    gid = uuid4()
    row = _membership_mapping(gid)
    out = await OidcMappingService(fake_session(gets=[row])).update_membership_mapping(
        row.id, GremiumMembershipMappingUpdate(oidcGroup="other"), "admin"
    )
    assert (out.gremium_id, out.oidc_group) == (gid, "other")


async def test_delete_membership_mapping(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    row = _membership_mapping(uuid4())
    db = fake_session(gets=[row])
    await OidcMappingService(db).delete_membership_mapping(row.id, "admin")
    assert row in db.deleted and synced == [db] and db.committed == 1
    assert audits[0]["target_id"] == str(row.id)


async def test_delete_membership_mapping_not_found() -> None:
    with pytest.raises(NotFoundError):
        await OidcMappingService(fake_session(gets=[None])).delete_membership_mapping(
            uuid4(), "admin"
        )


# ---------------------------------------------------------------- role mappings


async def test_list_role_mappings_carries_gremium_of_role() -> None:
    gid = uuid4()
    m = _role_mapping(uuid4())
    out = await OidcMappingService(fake_session(result((m, gid)))).list_role_mappings()
    assert [(o.gremium_id, o.gremium_role_id, o.oidc_group) for o in out] == [
        (gid, m.gremium_role_id, "stupa-board")
    ]


async def test_create_role_mapping_unknown_role() -> None:
    svc = OidcMappingService(fake_session(gets=[None]))
    payload = GremiumRoleMappingCreate(oidcGroup="x", gremiumRoleId=uuid4())
    with pytest.raises(NotFoundError, match="gremium role"):
        await svc.create_role_mapping(payload, "admin")


async def test_create_role_mapping_audits_syncs_commits(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    role = _role(key="vorstand")
    db = fake_session(gets=[role])
    _ids_on_flush(db)
    payload = GremiumRoleMappingCreate(oidcGroup="stupa-board", gremiumRoleId=role.id)
    out = await OidcMappingService(db).create_role_mapping(payload, "admin")
    assert (out.gremium_id, out.gremium_role_id) == (role.gremium_id, role.id)
    assert audits[0]["target_type"] == "gremium_role_mapping"
    assert synced == [db] and db.committed == 1


async def test_create_role_mapping_duplicate_409(synced: list[Any]) -> None:
    role = _role()
    db = fake_session(gets=[role])
    rollbacks = _raise_on_flush(db)
    payload = GremiumRoleMappingCreate(oidcGroup="x", gremiumRoleId=role.id)
    with pytest.raises(ConflictError, match="already maps"):
        await OidcMappingService(db).create_role_mapping(payload, "admin")
    assert rollbacks == [1] and synced == []


async def test_update_role_mapping_not_found() -> None:
    with pytest.raises(NotFoundError):
        await OidcMappingService(fake_session(gets=[None])).update_role_mapping(
            uuid4(), GremiumRoleMappingUpdate(oidcGroup="x"), "admin"
        )


async def test_update_role_mapping_changes_role_and_group(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    row = _role_mapping(uuid4())
    new_role = _role(key="manager")
    db = fake_session(gets=[row, new_role])
    out = await OidcMappingService(db).update_role_mapping(
        row.id, GremiumRoleMappingUpdate(oidcGroup="m", gremiumRoleId=new_role.id), "admin"
    )
    assert (out.gremium_role_id, out.gremium_id, out.oidc_group) == (
        new_role.id,
        new_role.gremium_id,
        "m",
    )
    assert synced == [db]


async def test_update_role_mapping_group_only_reads_current_role(
    audits: list[dict[str, Any]], synced: list[Any]
) -> None:
    role = _role()
    row = _role_mapping(role.id)
    out = await OidcMappingService(fake_session(gets=[row, role])).update_role_mapping(
        row.id, GremiumRoleMappingUpdate(oidcGroup="other"), "admin"
    )
    assert (out.gremium_role_id, out.gremium_id) == (role.id, role.gremium_id)


async def test_delete_role_mapping(audits: list[dict[str, Any]], synced: list[Any]) -> None:
    row = _role_mapping(uuid4())
    db = fake_session(gets=[row])
    await OidcMappingService(db).delete_role_mapping(row.id, "admin")
    assert row in db.deleted and synced == [db] and db.committed == 1


async def test_delete_role_mapping_not_found() -> None:
    with pytest.raises(NotFoundError):
        await OidcMappingService(fake_session(gets=[None])).delete_role_mapping(
            uuid4(), "admin"
        )


async def test_delete_gremium_role_in_use_by_mapping_blocked() -> None:
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


async def test_sync_role_group_alone_gives_no_membership(
    audits: list[dict[str, Any]],
) -> None:
    row = _principal(["stupa-board"])
    db = fake_session(result(), result())  # no membership mapping, no membership
    assert await membership_sync.sync_principal_memberships(db, row) is False
    assert db.added == []


async def test_sync_member_without_role_mapping_gets_member_role(
    audits: list[dict[str, Any]],
) -> None:
    row = _principal(["stupa"])
    gid = uuid4()
    member = _role(gid, key="member")
    db = fake_session(
        result(gid),  # membership mappings -> gremien
        result(),  # role mappings -> none
        result(member),  # default role lookup
        result(),  # existing memberships
    )
    _ids_on_flush(db)
    assert await membership_sync.sync_principal_memberships(db, row) is True
    [added] = db.added
    assert (added.principal_id, added.gremium_id, added.gremium_role_id) == (
        row.id,
        gid,
        member.id,
    )
    assert len(audits) == 1


async def test_sync_creates_missing_member_role(
    audits: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _principal(["stupa"])
    gid = uuid4()
    member = _role(gid, key="member")
    ensured: list[UUID] = []

    async def _ensure(self: Any, gremium_id: UUID) -> bool:
        ensured.append(gremium_id)
        return True

    monkeypatch.setattr(GremiumRoleService, "ensure_forced_roles", _ensure)
    db = fake_session(result(gid), result(), result(), result(member), result())
    _ids_on_flush(db)
    await membership_sync.sync_principal_memberships(db, row)
    assert ensured == [gid]
    assert db.added[0].gremium_role_id == member.id


async def test_sync_role_mapping_applies_to_member(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa", "stupa-board"])
    gid = uuid4()
    board = _role(gid, key="vorstand", perms=["vote.cast", "vote.manage"])
    current = _membership(row.id, gid, uuid4())
    db = fake_session(result(gid), result(board), result(current))
    assert await membership_sync.sync_principal_memberships(db, row) is True
    assert current.gremium_role_id == board.id
    assert db.added == [] and db.deleted == []


async def test_sync_no_change_is_a_noop(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa", "stupa-board"])
    gid = uuid4()
    board = _role(gid, key="vorstand")
    current = _membership(row.id, gid, board.id)
    db = fake_session(result(gid), result(board), result(current))
    assert await membership_sync.sync_principal_memberships(db, row) is False
    assert audits == [] and db.flushed == 0


async def test_sync_drops_duplicate_row_of_one_gremium(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa", "stupa-board"])
    gid = uuid4()
    role = _role(gid, key="vorstand")
    first = _membership(row.id, gid, role.id)
    second = _membership(row.id, gid, role.id)
    db = fake_session(result(gid), result(role), result(first, second))
    assert await membership_sync.sync_principal_memberships(db, row) is True
    assert db.deleted == [second]


async def test_sync_prefers_role_with_more_permissions(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa", "a", "b"])
    gid = uuid4()
    small = _role(gid, key="protokoll", perms=["protocol.write"])
    big = _role(gid, key="vorstand", perms=["vote.cast", "session.manage"])
    db = fake_session(result(gid), result(small, big), result())
    _ids_on_flush(db)
    await membership_sync.sync_principal_memberships(db, row)
    assert db.added[0].gremium_role_id == big.id


async def test_sync_tie_breaks_on_lower_key(audits: list[dict[str, Any]]) -> None:
    row = _principal(["stupa", "a", "b"])
    gid = uuid4()
    manager = _role(gid, key="manager", perms=["vote.cast"])
    alpha = _role(gid, key="alpha", perms=["vote.manage"])
    db = fake_session(result(gid), result(manager, alpha), result())
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
