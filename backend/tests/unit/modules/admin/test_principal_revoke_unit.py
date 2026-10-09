"""Revoke rights ("Rechte entziehen") without a database.

The pure functions (targets of a group, preview, plan, list filters) run on a
hand-built snapshot. The service runs on a queue session: each `execute`/`scalars`
call pops the next result. The name lookups, the mail data, the audit service and
the membership sync are replaced in the module. The routes run with a fake service
and their permission gate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin import principal_revoke as mod
from app.modules.admin.principal_revoke import (
    AssignmentFact,
    DelegationFact,
    MembershipFact,
    PoolFact,
    PrincipalRevokeService,
    RoleInfo,
    Snapshot,
    build_preview,
    group_targets,
    has_groups_filter,
    held_roles,
    last_login_filter,
    plan_revoke,
    principals_with_access,
    tied_gremien,
)
from app.modules.admin.router import get_principal_revoke_service
from app.modules.admin.schemas import (
    PrincipalRevokeIn,
    RevokePreviewOut,
    RevokePrincipalOut,
    RevokeResultOut,
)
from app.modules.audit.actions import AuditAction
from app.modules.auth.identity import PrincipalRef
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications.auto import DelegationMailInfo
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests._support.auth_fakes import FakeResult

PID = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)
THIRD = uuid.UUID(int=3)
G_FS = uuid.UUID(int=10)  # Fachschaft Informatik
G_SP = uuid.UUID(int=11)  # Studierendenparlament
G_TE = uuid.UUID(int=12)  # Fachschaft Technik (role mapping only, no tie)
R_HHB = RoleInfo(uuid.UUID(int=20), "hhb", {"de": "Haushaltsbeauftragte"})
R_MEMBER = RoleInfo(uuid.UUID(int=21), "member", {"de": "Mitglied"})
R_ADMIN = RoleInfo(uuid.UUID(int=22), "admin", {"de": "Administration"})
GR_VORSITZ = RoleInfo(uuid.UUID(int=30), "vorsitz", {"de": "Vorsitz"})
GR_MEMBER = RoleInfo(uuid.UUID(int=31), "member", {"de": "Mitglied"})
GR_TE = uuid.UUID(int=32)


def _snap(**kw: Any) -> Snapshot:
    """The person of the mockup: Tobias Kern with two Gremien and one global role."""
    base: dict[str, Any] = {
        "principal_id": PID,
        "groups": ["fs-informatik", "fs-informatik-vorsitz", "haushalt", "stray"],
        "memberships": [MembershipFact(G_FS, GR_VORSITZ)],
        "assignments": [
            AssignmentFact(uuid.UUID(int=40), GR_MEMBER, G_SP, "boss", None, None),
            AssignmentFact(uuid.UUID(int=41), R_MEMBER, None, "bootstrap", None, None),
            AssignmentFact(
                uuid.UUID(int=42),
                R_ADMIN,
                None,
                "bootstrap",
                datetime(2025, 11, 4, tzinfo=UTC),
                None,
            ),
        ],
        "pool": [
            PoolFact(uuid.UUID(int=50), G_FS, OTHER, PID),
            PoolFact(uuid.UUID(int=51), G_SP, None, PID),
            PoolFact(uuid.UUID(int=52), G_FS, PID, THIRD),
        ],
        "delegations": [
            DelegationFact(
                uuid.UUID(int=60), G_FS, uuid.UUID(int=70), "Sitzung 1", date(2026, 10, 17),
                "planned", OTHER, PID, True,
            ),
            DelegationFact(
                uuid.UUID(int=61), G_FS, uuid.UUID(int=71), "Sitzung 2", None,
                "live", PID, THIRD, False,
            ),
        ],
        "membership_maps": [("fs-informatik", G_FS)],
        "role_maps": [
            ("fs-informatik-vorsitz", G_FS, GR_VORSITZ.id),
            ("fs-informatik-vorsitz", G_TE, GR_TE),
        ],
        "group_maps": [("haushalt", R_HHB), ("fs-informatik", R_MEMBER)],
        "gremium_names": {G_FS: "Fachschaft Informatik", G_SP: "Studierendenparlament"},
        "names": {OTHER: "Jonas Weber", THIRD: "Rana Becker"},
        "grantor_names": {"boss": "Mara Keller"},
        "open_tasks": {G_FS: 2},
    }
    base.update(kw)
    return Snapshot(**base)


def _row(**kw: Any) -> PrincipalRow:
    row = PrincipalRow(
        sub=kw.get("sub", "tk"),
        email="tobias.kern@student.example",
        display_name="Tobias Kern",
        oidc_groups=kw.get("groups", ["fs-informatik", "haushalt", "stray"]),
    )
    row.id = PID
    row.last_login = datetime(2026, 2, 12, tzinfo=UTC)
    row.active = kw.get("active", True)
    row.merged_into = kw.get("merged_into")
    return row


# -- Pure logic --------------------------------------------------------------------------


def test_held_roles_skip_member_and_gremium_rows() -> None:
    assert set(held_roles(_snap())) == {R_HHB.id, R_ADMIN.id}


def test_tied_gremien_cover_every_source() -> None:
    assert tied_gremien(_snap()) == {G_FS, G_SP}
    only_delegation = _snap(
        memberships=[], assignments=[], pool=[], membership_maps=[],
        delegations=[_snap().delegations[0]],
    )
    assert tied_gremien(only_delegation) == {G_FS}


def test_group_targets_ignore_untied_role_maps_member_and_foreign_groups() -> None:
    snap = _snap(membership_maps=[("fs-informatik", G_FS), ("not-mine", G_SP)])
    targets = group_targets(snap)
    assert targets == {
        "fs-informatik": ({G_FS}, set()),
        "fs-informatik-vorsitz": ({G_FS}, set()),
        "haushalt": (set(), {R_HHB.id}),
    }
    # A role mapping counts only for a tied Gremium, a foreign group never.
    snap = _snap(
        role_maps=[("not-mine", G_FS, GR_VORSITZ.id)], group_maps=[("not-mine", R_HHB)]
    )
    assert "not-mine" not in group_targets(snap)


def test_build_preview_groups_everything_by_gremium() -> None:
    out = build_preview(_snap(), _row(), is_self=False)
    assert out.principal.display_name == "Tobias Kern"
    assert out.principal.last_login == "2026-02-12T00:00:00+00:00"
    assert out.is_self is False
    assert [g.name for g in out.gremien] == ["Fachschaft Informatik", "Studierendenparlament"]
    fs, sp = out.gremien
    assert fs.membership is not None
    assert fs.membership.role_key == "vorsitz"
    assert fs.membership.groups == ["fs-informatik", "fs-informatik-vorsitz"]
    assert fs.groups == ["fs-informatik", "fs-informatik-vorsitz"]
    assert fs.open_tasks == 2
    # As substitute for Jonas Weber, and as the member that Rana Becker represents.
    assert [(p.as_substitute, p.member_name, p.substitute_name) for p in fs.pool_entries] == [
        (True, "Jonas Weber", None),
        (False, None, "Rana Becker"),
    ]
    assert [(d.as_delegator, d.other_name, d.meeting_date) for d in fs.planned_delegations] == [
        (False, "Jonas Weber", "2026-10-17")
    ]
    assert [(d.as_delegator, d.other_name, d.meeting_date) for d in fs.live_delegations] == [
        (True, "Rana Becker", None)
    ]
    assert sp.membership is None and sp.open_tasks == 0
    assert [a.granted_by for a in sp.assignments] == ["Mara Keller"]
    assert sp.pool_entries[0].gremium_wide is True
    assert [r.role_key for r in out.global_roles] == ["admin", "hhb"]
    admin, hhb = out.global_roles
    assert admin.groups == [] and [a.granted_by for a in admin.assignments] == ["bootstrap"]
    assert admin.assignments[0].valid_from == "2025-11-04T00:00:00+00:00"
    assert hhb.groups == ["haushalt"] and hhb.assignments == []
    assert [(g.group, g.gremium_ids, g.global_role_ids) for g in out.groups] == [
        ("fs-informatik", [G_FS], []),
        ("fs-informatik-vorsitz", [G_FS], []),
        ("haushalt", [], [R_HHB.id]),
    ]
    dumped = out.model_dump(by_alias=True)
    assert dumped["globalRoles"][0]["roleKey"] == "admin"
    assert dumped["gremien"][0]["poolEntries"][0]["asSubstitute"] is True


def test_build_preview_unknown_gremium_name_and_inactive_account() -> None:
    out = build_preview(_snap(gremium_names={}), _row(active=False), is_self=True)
    assert {g.name for g in out.gremien} == {""}
    assert out.principal.active is False and out.is_self is True


def test_plan_needs_a_selection() -> None:
    with pytest.raises(ValidationProblem) as exc:
        plan_revoke(_snap(), [], [], deactivate=False)
    assert exc.value.code == "revoke_empty"
    plan = plan_revoke(_snap(), [], [], deactivate=True)
    assert plan.removed_groups == [] and plan.assignments == []


def test_plan_refuses_unknown_targets() -> None:
    with pytest.raises(ValidationProblem) as exc:
        plan_revoke(_snap(), [G_TE], [R_MEMBER.id], deactivate=False)
    assert exc.value.code == "revoke_unknown_target"
    assert [(e.field, e.msg) for e in exc.value.errors or []] == [
        ("gremiumIds", str(G_TE)),
        ("globalRoleIds", str(R_MEMBER.id)),
    ]


def test_plan_refuses_a_half_selection_of_a_shared_group() -> None:
    # `shared` leads into both Gremien and to the global role.
    snap = _snap(
        groups=["shared"],
        membership_maps=[("shared", G_FS), ("shared", G_SP)],
        role_maps=[],
        group_maps=[("shared", R_HHB)],
    )
    with pytest.raises(ValidationProblem) as exc:
        plan_revoke(snap, [G_FS], [], deactivate=False)
    assert exc.value.code == "revoke_incomplete"
    assert [(e.field, e.msg) for e in exc.value.errors or []] == [
        ("gremiumIds", str(G_SP)),
        ("globalRoleIds", str(R_HHB.id)),
    ]
    with pytest.raises(ValidationProblem):
        plan_revoke(snap, [], [R_HHB.id], deactivate=False)
    plan = plan_revoke(snap, [G_FS, G_SP, G_FS], [R_HHB.id], deactivate=False)
    assert plan.gremium_ids == [G_FS, G_SP]
    assert plan.removed_groups == ["shared"]


def test_plan_clears_a_gremium_completely_and_keeps_live_delegations() -> None:
    plan = plan_revoke(_snap(), [G_FS], [], deactivate=False)
    assert plan.removed_groups == ["fs-informatik", "fs-informatik-vorsitz"]
    assert plan.assignments == []
    assert [p.id for p in plan.pool] == [uuid.UUID(int=50), uuid.UUID(int=52)]
    assert [d.id for d in plan.delegations] == [uuid.UUID(int=60)]
    assert plan.kept_live == 1


def test_plan_global_roles_remove_groups_and_manual_rows() -> None:
    plan = plan_revoke(_snap(), [G_SP], [R_HHB.id, R_ADMIN.id], deactivate=False)
    assert plan.removed_groups == ["haushalt"]
    assert [a.id for a in plan.assignments] == [uuid.UUID(int=40), uuid.UUID(int=42)]
    assert [p.id for p in plan.pool] == [uuid.UUID(int=51)]
    assert plan.delegations == [] and plan.kept_live == 0


def _sql(clause: Any) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))


def test_last_login_filter_branches() -> None:
    assert last_login_filter(None, False) is None
    assert _sql(last_login_filter(None, True)) == "principal.last_login IS NULL"
    older = _sql(last_login_filter(date(2026, 7, 1), False))
    assert "principal.last_login <" in older and "IS NULL" not in older
    both = _sql(last_login_filter(date(2026, 7, 1), True))
    assert "principal.last_login <" in both and "OR principal.last_login IS NULL" in both


def test_has_groups_filter_branches() -> None:
    assert has_groups_filter(None) is None
    yes = _sql(has_groups_filter(True))
    assert "jsonb_typeof" in yes and "jsonb_array_length" in yes and "END >" in yes
    assert "END =" in _sql(has_groups_filter(False))


# -- Queue session -----------------------------------------------------------------------


class _Session:
    """Pop one queued result per `execute`/`scalars` call and record the statements."""

    def __init__(self, *results: list[Any]) -> None:
        self._results = [FakeResult(r) for r in results]
        self.statements: list[Any] = []
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0

    async def _next(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        return self._results.pop(0) if self._results else FakeResult()

    async def execute(self, stmt: Any) -> FakeResult:
        return await self._next(stmt)

    async def scalars(self, stmt: Any) -> FakeResult:
        return await self._next(stmt)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


async def test_principals_with_access() -> None:
    assert await principals_with_access(_Session(), []) == set()  # type: ignore[arg-type]
    db = _Session([PID, None])
    assert await principals_with_access(db, [PID, OTHER]) == {PID}  # type: ignore[arg-type]
    assert "UNION" in _sql(db.statements[0])


async def test_principal_not_found_and_merged() -> None:
    with pytest.raises(NotFoundError):
        await PrincipalRevokeService(_Session([])).preview(PID, actor="boss")  # type: ignore[arg-type]
    merged = _row(merged_into=OTHER)
    with pytest.raises(ConflictError) as exc:
        await PrincipalRevokeService(_Session([merged])).preview(PID, actor="boss")  # type: ignore[arg-type]
    assert exc.value.code == "principal_merged"


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[set[Any]]:
    """Replace the two name lookups; record what they were asked for."""
    asked: list[set[Any]] = []

    async def by_id(_s: Any, ids: Any) -> dict[uuid.UUID, PrincipalRef]:
        asked.append(set(ids))
        return {i: PrincipalRef(id=i, display_name=f"P{i.int}", email=None) for i in ids}

    async def by_sub(_s: Any, subs: Any) -> dict[str, PrincipalRef]:
        asked.append(set(subs))
        return {s: PrincipalRef(id=OTHER, display_name="Mara Keller", email=None) for s in subs}

    monkeypatch.setattr(mod, "refs_by_id", by_id)
    monkeypatch.setattr(mod, "refs_by_sub", by_sub)
    return asked


class _Obj:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _full_queue(row: PrincipalRow) -> list[list[Any]]:
    """The answers of a snapshot load with groups, in statement order."""
    membership = _Obj(gremium_id=G_FS)
    grole = _Obj(id=GR_VORSITZ.id, key="vorsitz", name_i18n={"de": "Vorsitz"})
    assignment = _Obj(
        id=uuid.UUID(int=40), gremium_id=G_SP, granted_by="boss", valid_from=None,
        valid_until=None,
    )
    role = _Obj(id=GR_MEMBER.id, key="member", name_i18n=None)
    pool = _Obj(
        id=uuid.UUID(int=50), gremium_id=G_FS, member_principal_id=OTHER,
        substitute_principal_id=PID,
    )
    deleg = _Obj(
        id=uuid.UUID(int=60), gremium_id=G_FS, delegator_principal_id=OTHER,
        delegate_principal_id=PID, delegate_voting=True,
    )
    meeting = _Obj(
        id=uuid.UUID(int=70), title="Sitzung 1", date=date(2026, 10, 17), status="planned"
    )
    hhb = _Obj(id=R_HHB.id, key="hhb", name_i18n={"de": "HHB"})
    return [
        [row],  # the principal
        [(membership, grole)],
        [(assignment, role)],
        [pool],
        [(deleg, meeting)],
        [("fs-informatik", G_FS)],
        [("fs-informatik-vorsitz", G_FS, GR_VORSITZ.id)],
        [("haushalt", hhb)],
        [(G_FS, "Fachschaft Informatik"), (G_SP, "Studierendenparlament")],
        [(str(G_FS), 3), ("unknown", 1)],  # open votes
    ]


async def test_preview_loads_the_snapshot(lookups: list[set[Any]]) -> None:
    row = _row(groups=["fs-informatik", "fs-informatik-vorsitz", "haushalt"])
    db = _Session(*_full_queue(row))
    out = await PrincipalRevokeService(db).preview(PID, actor="tk")  # type: ignore[arg-type]
    assert out.is_self is True
    assert [g.name for g in out.gremien] == ["Fachschaft Informatik", "Studierendenparlament"]
    fs = out.gremien[0]
    assert fs.membership is not None and fs.membership.groups == [
        "fs-informatik",
        "fs-informatik-vorsitz",
    ]
    assert fs.open_tasks == 3
    assert fs.pool_entries[0].member_name == f"P{OTHER.int}"
    assert fs.planned_delegations[0].voting is True
    assert out.gremien[1].assignments[0].granted_by == "Mara Keller"
    assert out.gremien[1].assignments[0].role_label == {}
    assert [r.role_key for r in out.global_roles] == ["hhb"]
    assert lookups == [{OTHER}, {"boss"}]
    assert len(db.statements) == 10


async def test_snapshot_without_groups_and_ties_skips_the_lookups(
    lookups: list[set[Any]],
) -> None:
    row = _row(groups=None)
    db = _Session([row], [], [], [], [])
    out = await PrincipalRevokeService(db).preview(PID, actor="boss")  # type: ignore[arg-type]
    assert out.gremien == [] and out.global_roles == [] and out.groups == []
    # The principal, memberships, assignments, pool, delegations: nothing else.
    assert len(db.statements) == 5
    assert lookups == [set(), set()]


# -- Revoke ------------------------------------------------------------------------------


class _Audit:
    entries: list[dict[str, Any]] = []

    def __init__(self, _session: Any) -> None:
        pass

    async def record(self, **kw: Any) -> None:
        _Audit.entries.append(kw)


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch, lookups: list[set[Any]]) -> list[str]:
    """Replace the audit service, the membership sync and the mail data."""
    calls: list[str] = []
    _Audit.entries = []
    monkeypatch.setattr(mod, "AuditService", _Audit)

    async def sync(_s: Any, row: PrincipalRow) -> bool:
        calls.append(f"sync:{sorted(row.oidc_groups or [])}")
        return True

    async def mail(_s: Any, delegation_id: uuid.UUID) -> DelegationMailInfo:
        calls.append(f"mail:{delegation_id.int}")
        return DelegationMailInfo(delegation_id, "x@y.de", "Sitzung 1", None, None, None, True)

    monkeypatch.setattr(mod, "sync_principal_memberships", sync)
    monkeypatch.setattr(mod, "meeting_delegation_mail_info", mail)
    return calls


async def test_revoke_refuses_the_own_account(writes: list[str]) -> None:
    db = _Session([_row(sub="boss")])
    with pytest.raises(ConflictError) as exc:
        await PrincipalRevokeService(db).revoke(  # type: ignore[arg-type]
            PID, PrincipalRevokeIn.model_validate({"gremiumIds": [G_FS]}), actor="boss"
        )
    assert exc.value.code == "revoke_own_account"
    assert db.rolled_back == 1 and db.committed == 0
    assert "FOR UPDATE" in _sql(db.statements[0])


async def test_revoke_rolls_back_on_an_invalid_selection(writes: list[str]) -> None:
    row = _row(groups=["fs-informatik", "fs-informatik-vorsitz", "haushalt"])
    db = _Session(*_full_queue(row))
    with pytest.raises(ValidationProblem):
        await PrincipalRevokeService(db).revoke(  # type: ignore[arg-type]
            PID, PrincipalRevokeIn.model_validate({"gremiumIds": [G_TE]}), actor="boss"
        )
    assert db.rolled_back == 1 and db.committed == 0 and writes == []


async def test_revoke_clears_the_gremium_and_deactivates(writes: list[str]) -> None:
    row = _row(groups=["fs-informatik", "fs-informatik-vorsitz", "haushalt"])
    db = _Session(*_full_queue(row))
    out, mails = await PrincipalRevokeService(db).revoke(  # type: ignore[arg-type]
        PID,
        PrincipalRevokeIn.model_validate(
            {"gremiumIds": [G_FS, G_SP], "globalRoleIds": [R_HHB.id], "deactivate": True}
        ),
        actor="boss",
    )
    assert out.removed_groups == ["fs-informatik", "fs-informatik-vorsitz", "haushalt"]
    assert (out.deleted_assignments, out.deleted_pool_entries, out.revoked_delegations) == (1, 1, 1)
    assert out.kept_live_delegations == 0 and out.deactivated is True
    assert row.oidc_groups == [] and row.active is False
    assert [m.delegation_id if m else None for m in mails] == [uuid.UUID(int=60)]
    assert writes == ["mail:60", "sync:[]"]
    assert db.committed == 1 and db.rolled_back == 0
    deletes = [_sql(s) for s in db.statements[10:]]
    assert [d.split()[2] for d in deletes] == [
        "role_assignment",
        "delegation_substitute",
        "meeting_delegation",
    ]
    actions = [e["action"] for e in _Audit.entries]
    assert actions == [
        AuditAction.DELEGATION_REVOKE,
        AuditAction.ROLE_CHANGE,
        AuditAction.PRINCIPAL_ACCESS_REVOKE,
    ]
    assert _Audit.entries[0]["data"]["byAccessRevoke"] is True
    data = _Audit.entries[2]["data"]
    assert data["removedGroups"] == out.removed_groups
    assert data["deactivate"] is True
    assert data["delegationIds"] == [str(uuid.UUID(int=60))]


async def test_revoke_deactivate_only_on_an_inactive_account(writes: list[str]) -> None:
    row = _row(groups=None, active=False)
    db = _Session([row], [], [], [], [])
    out, mails = await PrincipalRevokeService(db).revoke(  # type: ignore[arg-type]
        PID, PrincipalRevokeIn(deactivate=True), actor="boss"
    )
    assert out.deactivated is False and mails == []
    assert row.oidc_groups is None
    assert [e["action"] for e in _Audit.entries] == [AuditAction.PRINCIPAL_ACCESS_REVOKE]
    assert db.committed == 1


# -- Routes ------------------------------------------------------------------------------


class _FakeRevoke:
    def __init__(self) -> None:
        self.calls: list[tuple[str, uuid.UUID, str]] = []

    async def preview(self, pid: uuid.UUID, *, actor: str) -> RevokePreviewOut:
        self.calls.append(("preview", pid, actor))
        return RevokePreviewOut(
            principal=RevokePrincipalOut(
                id=pid, display_name="Tobias Kern", email=None, last_login=None
            ),
            gremien=[],
            global_roles=[],
            groups=[],
            is_self=False,
        )

    async def revoke(
        self, pid: uuid.UUID, payload: PrincipalRevokeIn, *, actor: str
    ) -> tuple[RevokeResultOut, list[DelegationMailInfo | None]]:
        self.calls.append(("revoke", pid, actor))
        return (
            RevokeResultOut(
                gremium_ids=payload.gremium_ids,
                global_role_ids=payload.global_role_ids,
                removed_groups=["fs-informatik"],
                deleted_assignments=0,
                deleted_pool_entries=1,
                revoked_delegations=1,
                kept_live_delegations=0,
                deactivated=payload.deactivate,
            ),
            [None],
        )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, _FakeRevoke, list[Any]]:
    application = create_app()
    fake = _FakeRevoke()
    application.dependency_overrides[get_principal_revoke_service] = lambda: fake
    mailed: list[Any] = []

    async def delegation_changed(_self: Any, _settings: Any, info: Any, **kw: Any) -> None:
        mailed.append((info, kw["granted"]))

    from app.modules.notifications.auto import AutoMailer

    monkeypatch.setattr(AutoMailer, "delegation_changed", delegation_changed)
    return application, fake, mailed


def _as(app: FastAPI, perms: set[str]) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="boss", permissions=perms
    )


def test_routes_call_the_service_and_mail(api: tuple[FastAPI, _FakeRevoke, list[Any]]) -> None:
    app, fake, mailed = api
    _as(app, {"admin.users.revoke_groups"})
    client = TestClient(app)
    got = client.get(f"/api/admin/principals/{PID}/revoke-preview")
    assert got.status_code == 200, got.text
    assert got.json()["principal"]["displayName"] == "Tobias Kern"
    assert got.json()["globalRoles"] == [] and got.json()["isSelf"] is False
    done = client.post(
        f"/api/admin/principals/{PID}/revoke",
        json={"gremiumIds": [str(G_FS)], "globalRoleIds": [], "deactivate": True},
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["gremiumIds"] == [str(G_FS)] and body["deactivated"] is True
    assert body["removedGroups"] == ["fs-informatik"]
    assert fake.calls == [("preview", PID, "boss"), ("revoke", PID, "boss")]
    assert mailed == [(None, False)]


@pytest.mark.parametrize("perms", [set(), {"admin.users"}, {"admin.users.merge"}])
def test_routes_need_the_revoke_permission(
    api: tuple[FastAPI, _FakeRevoke, list[Any]], perms: set[str]
) -> None:
    app, fake, _ = api
    _as(app, perms)
    client = TestClient(app)
    assert client.get(f"/api/admin/principals/{PID}/revoke-preview").status_code == 403
    assert client.post(f"/api/admin/principals/{PID}/revoke", json={}).status_code == 403
    assert fake.calls == []


def test_revoke_body_refuses_unknown_fields(api: tuple[FastAPI, _FakeRevoke, list[Any]]) -> None:
    app, _, _ = api
    _as(app, {"admin.users.revoke_groups"})
    client = TestClient(app)
    bad = client.post(f"/api/admin/principals/{PID}/revoke", json={"groups": ["x"]})
    assert bad.status_code == 422
    assert bad.headers["content-type"].startswith("application/problem+json")


def test_list_principals_passes_the_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.admin.router import get_config_service

    seen: dict[str, Any] = {}

    class _Config:
        async def search_principals(self, q: str | None, **kw: Any) -> list[Any]:
            seen.update(kw, q=q)
            return []

    app = create_app()
    app.dependency_overrides[get_config_service] = lambda: _Config()
    _as(app, {"admin.users"})
    client = TestClient(app)
    got = client.get(
        "/api/admin/principals?lastLoginBefore=2026-07-01&includeNever=true&hasGroups=true"
    )
    assert got.status_code == 200, got.text
    assert seen == {
        "q": None,
        "last_login_before": date(2026, 7, 1),
        "include_never": True,
        "has_groups": True,
    }
    assert client.get("/api/admin/principals?lastLoginBefore=gestern").status_code == 422


def test_revoke_permission_is_in_no_oauth_scope() -> None:
    from app.modules.auth.oauth import FORBIDDEN_PERMISSIONS, SCOPES, scope_permissions
    from app.shared.permissions import PERMISSION_CATALOGUE

    key = "admin.users.revoke_groups"
    assert key in PERMISSION_CATALOGUE
    assert all(key not in perms for perms in SCOPES.values())
    assert key in FORBIDDEN_PERMISSIONS
    assert key not in scope_permissions(list(SCOPES))


async def test_search_principals_filters_and_has_access() -> None:
    from app.modules.admin.service import ConfigService
    from tests._support.auth_fakes import fake_session, result

    with_groups, plain, tied = _row(), _row(groups=None), _row(groups=[])
    plain.id, tied.id = OTHER, THIRD
    db = fake_session(result(with_groups, plain, tied), result(), result(THIRD))
    out = await ConfigService(db).search_principals(
        None, last_login_before=date(2026, 7, 1), include_never=True, has_groups=False
    )
    assert [p.has_access for p in out] == [True, False, True]
    assert out[0].model_dump(by_alias=True)["hasAccess"] is True
