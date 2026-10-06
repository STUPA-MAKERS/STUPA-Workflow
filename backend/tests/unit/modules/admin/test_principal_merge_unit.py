"""Account merge without a database: the service branches and the route wiring.

The integration suite (`tests/integration/modules/admin/test_principal_merge.py`) runs
the SQL against Postgres. These tests cover the control flow with a fake session:
the preconditions, the conflict refusal, the counts, the audit entry, the rollback on
an error and on a unique-key clash, and the two routes with their permission gate.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.sql.dml import Delete, Update

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin import principal_merge as merge_mod
from app.modules.admin.principal_merge import AREAS, PrincipalMergeService
from app.modules.admin.router import get_principal_merge_service
from app.modules.admin.schemas import (
    MergeAreaOut,
    MergeConflictOut,
    MergePermissionOut,
    MergePreviewOut,
    MergePrincipalOut,
    MergeResultOut,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

OLD = uuid.UUID(int=1)
NEW = uuid.UUID(int=2)


class _Row:
    def __init__(self, pid: uuid.UUID, sub: str, **kw: Any) -> None:
        self.id = pid
        self.sub = sub
        self.display_name = kw.get("display_name", sub.title())
        self.email = kw.get("email")
        self.last_login = kw.get("last_login")
        self.merged_into = kw.get("merged_into")
        self.merged_at = None
        self.active = True
        self.calendar_token = kw.get("calendar_token")


class _Result:
    def __init__(self, rows: Iterable[Any] = (), rowcount: int = 0) -> None:
        self._rows = list(rows)
        self.rowcount = rowcount

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    """Answer the merge statements by their kind.

    `scalars` gives the principals. `scalar` gives a count. `execute` gives the
    conflict labels from a queue for a SELECT, and a rowcount for an UPDATE or a
    DELETE. `fail_on` raises on the n-th DML statement.
    """

    def __init__(
        self,
        principals: list[_Row],
        *,
        count: int = 0,
        rowcount: int = 0,
        conflict_rows: list[list[tuple[str | None]]] | None = None,
        fail_on: int | None = None,
        fail_with: BaseException | None = None,
    ) -> None:
        self.principals = principals
        self.count = count
        self.rowcount = rowcount
        self.conflict_rows = list(conflict_rows or [])
        self.fail_on = fail_on
        self.fail_with = fail_with
        self.dml = 0
        self.statements: list[Any] = []
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0

    async def scalars(self, stmt: Any) -> Any:
        self.statements.append(stmt)

        class _S:
            def __init__(self, rows: list[_Row]) -> None:
                self._rows = rows

            def all(self) -> list[_Row]:
                return self._rows

        return _S(self.principals)

    async def scalar(self, stmt: Any) -> int:
        self.statements.append(stmt)
        return self.count

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        if isinstance(stmt, (Update, Delete)):
            self.dml += 1
            if self.fail_on is not None and self.dml == self.fail_on:
                assert self.fail_with is not None
                raise self.fail_with
            return _Result(rowcount=self.rowcount)
        return _Result(self.conflict_rows.pop(0) if self.conflict_rows else [])

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


@pytest.fixture(autouse=True)
def _no_erasure_no_extra_rights(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By default no account is erased and the source holds no extra right.

    The tests of these two rules opt out with the marker ``real_rules``.
    """
    if request.node.get_closest_marker("real_rules"):
        return

    async def not_erased(_self: object, _ids: object) -> bool:
        return False

    async def no_extra(_self: object, *_a: object) -> tuple[list[object], bool]:
        return [], True

    monkeypatch.setattr(PrincipalMergeService, "_erased", not_erased)
    monkeypatch.setattr(PrincipalMergeService, "_privileges", no_extra)


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the membership sync and the audit hook. Collect the audit entries."""
    entries: list[dict[str, Any]] = []

    async def no_sync(*_a: object, **_k: object) -> bool:
        return True

    class _Audit:
        def __init__(self, _session: object) -> None:
            pass

        async def record(self, **kw: Any) -> None:
            entries.append(kw)

    monkeypatch.setattr(merge_mod, "sync_principal_memberships", no_sync)
    monkeypatch.setattr(merge_mod, "AuditService", _Audit)
    return entries


def _any(row: object) -> Any:
    """A row double where the service expects an ORM row."""
    return row


def _pair(**old_kw: Any) -> list[_Row]:
    return [_Row(OLD, "old", **old_kw), _Row(NEW, "new")]


def _svc(session: _Session) -> PrincipalMergeService:
    return PrincipalMergeService(session)  # type: ignore[arg-type]


async def test_preview_counts_every_area() -> None:
    session = _Session(_pair(calendar_token="tok"), count=2)
    out = await _svc(session).preview(OLD, NEW, actor="admin")
    # The fake count also answers the open erasure requests: two of them.
    assert out.can_merge is False
    assert [c.kind for c in out.conflicts] == ["erasure_open", "erasure_open"]
    areas = {a.area: a for a in out.areas}
    assert list(areas) == list(AREAS)
    assert areas["applications"].rewritten == 2 * 3
    # Notifications: two duplicates of two rows, so nothing is left to rewrite.
    assert areas["notifications"].combined == 2
    assert areas["notifications"].rewritten == 0
    assert areas["sessions"].removed == 2 * 3
    assert areas["memberships"].removed == 2
    assert areas["calendar"].removed == 1
    # The preview never locks, writes or commits.
    assert session.dml == 0
    assert session.committed == 0
    assert "FOR UPDATE" not in str(session.statements[0])


async def test_preview_lists_conflicts_with_labels() -> None:
    session = _Session(
        _pair(),
        count=1,
        conflict_rows=[[("Frage 1",)], [("Geheim",)], [("Sitzung A",)], [], [], [(None,)]],
    )
    out = await _svc(session).preview(OLD, NEW, actor="admin")
    assert out.can_merge is False
    assert [(c.kind, c.label) for c in out.conflicts] == [
        ("ballot_same_vote", "Frage 1"),
        ("ballot_same_vote", "Geheim"),
        ("delegation_same_meeting", "Sitzung A"),
        ("attendance_differs", None),
        ("erasure_open", None),
    ]


async def test_merge_applies_audits_and_commits(recorded: list[dict[str, Any]]) -> None:
    session = _Session(_pair(), count=0, rowcount=1)
    out = await _svc(session).merge(OLD, NEW, actor="admin")
    assert session.committed == 1
    assert session.rolled_back == 0
    assert "FOR UPDATE" in str(session.statements[0])
    areas = {a.area: a for a in out.areas}
    assert areas["votes"].rewritten == 2
    assert areas["sessions"].removed == 3
    assert areas["calendar"].removed == 0
    assert out.merged_at
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["actor"] == "admin"
    assert entry["action"] == "principal_merge"
    assert entry["target_id"] == str(OLD)
    assert entry["data"]["sourceId"] == str(OLD)
    assert entry["data"]["counts"]["votes"] == {"rewritten": 2}
    # Areas without a count stay out of the audit data.
    assert "calendar" not in entry["data"]["counts"]


async def test_merge_refuses_a_conflict(recorded: list[dict[str, Any]]) -> None:
    session = _Session(_pair(), conflict_rows=[[("Frage",)]])
    with pytest.raises(ConflictError) as exc:
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert exc.value.code == "merge_conflict"
    assert exc.value.errors is not None
    assert [(e.field, e.msg) for e in exc.value.errors] == [("ballot_same_vote", "Frage")]
    assert session.dml == 0
    assert session.committed == 0
    assert session.rolled_back == 1
    assert recorded == []


async def test_merge_maps_a_unique_clash_to_409(recorded: list[dict[str, Any]]) -> None:
    clash = IntegrityError("UPDATE ballot", {}, Exception("duplicate key"))
    session = _Session(_pair(), fail_on=3, fail_with=clash)
    with pytest.raises(ConflictError) as exc:
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert exc.value.code == "merge_conflict"
    assert exc.value.errors is None
    assert session.rolled_back == 1
    assert session.committed == 0


async def test_merge_rolls_back_on_any_error(recorded: list[dict[str, Any]]) -> None:
    session = _Session(_pair(), fail_on=1, fail_with=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert session.rolled_back == 1
    assert session.committed == 0


async def test_merge_refuses_the_own_account(recorded: list[dict[str, Any]]) -> None:
    session = _Session(_pair())
    with pytest.raises(ConflictError) as exc:
        await _svc(session).merge(OLD, NEW, actor="old")
    assert exc.value.code == "merge_own_account"
    assert session.rolled_back == 1


async def test_preconditions() -> None:
    with pytest.raises(ValidationProblem) as same:
        await _svc(_Session([])).preview(OLD, OLD, actor="admin")
    assert same.value.code == "merge_same_principal"
    with pytest.raises(NotFoundError):
        await _svc(_Session([_Row(NEW, "new")])).preview(OLD, NEW, actor="admin")
    with pytest.raises(NotFoundError):
        await _svc(_Session([_Row(OLD, "old")])).preview(OLD, NEW, actor="admin")
    with pytest.raises(ConflictError) as merged:
        await _svc(_Session(_pair(merged_into=uuid4()))).preview(OLD, NEW, actor="admin")
    assert merged.value.code == "principal_already_merged"
    target = _Row(NEW, "new", merged_into=uuid4())
    with pytest.raises(ConflictError) as tgt:
        await _svc(_Session([_Row(OLD, "old"), target])).preview(OLD, NEW, actor="admin")
    assert tgt.value.code == "merge_target_merged"


# -- Routes ------------------------------------------------------------------------------


def _person(pid: uuid.UUID, name: str) -> MergePrincipalOut:
    return MergePrincipalOut(id=pid, display_name=name, email=None, last_login=None)


class _FakeMerge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, uuid.UUID, uuid.UUID, str | None]] = []

    async def preview(self, source: uuid.UUID, target: uuid.UUID, *, actor: str) -> MergePreviewOut:
        self.calls.append(("preview", source, target, actor))
        return MergePreviewOut(
            source=_person(source, "Alt"),
            target=_person(target, "Neu"),
            areas=[MergeAreaOut(area="votes", rewritten=1)],
            conflicts=[MergeConflictOut(kind="erasure_open")],
            can_merge=False,
        )

    async def merge(self, source: uuid.UUID, target: uuid.UUID, *, actor: str) -> MergeResultOut:
        self.calls.append(("merge", source, target, actor))
        return MergeResultOut(
            source=_person(source, "Alt"),
            target=_person(target, "Neu"),
            areas=[MergeAreaOut(area="votes", rewritten=1)],
            merged_at=datetime(2026, 10, 5, tzinfo=UTC).isoformat(),
        )


@pytest.fixture
def api() -> tuple[FastAPI, _FakeMerge]:
    application = create_app()
    fake = _FakeMerge()
    application.dependency_overrides[get_principal_merge_service] = lambda: fake
    return application, fake


def _as(app: FastAPI, perms: set[str]) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="boss", permissions=perms
    )


def test_routes_call_the_service_in_camel_case(api: tuple[FastAPI, _FakeMerge]) -> None:
    app, fake = api
    _as(app, {"admin.users.merge"})
    client = TestClient(app)
    got = client.get(f"/api/admin/principals/{OLD}/merge-preview?targetId={NEW}")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["canMerge"] is False
    assert body["source"]["displayName"] == "Alt"
    assert body["conflicts"] == [{"kind": "erasure_open", "label": None}]
    done = client.post(f"/api/admin/principals/{OLD}/merge", json={"targetId": str(NEW)})
    assert done.status_code == 200, done.text
    assert done.json()["mergedAt"].startswith("2026-10-05")
    assert fake.calls == [("preview", OLD, NEW, "boss"), ("merge", OLD, NEW, "boss")]


@pytest.mark.parametrize("perms", [set(), {"admin.users"}, {"admin.users", "audit.read"}])
def test_routes_need_the_merge_permission(api: tuple[FastAPI, _FakeMerge], perms: set[str]) -> None:
    app, fake = api
    _as(app, perms)
    client = TestClient(app)
    preview = client.get(f"/api/admin/principals/{OLD}/merge-preview?targetId={NEW}")
    assert preview.status_code == 403
    assert (
        client.post(f"/api/admin/principals/{OLD}/merge", json={"targetId": str(NEW)}).status_code
        == 403
    )
    assert fake.calls == []


def test_merge_body_needs_a_target(api: tuple[FastAPI, _FakeMerge]) -> None:
    app, _ = api
    _as(app, {"admin.users.merge"})
    client = TestClient(app)
    assert client.post(f"/api/admin/principals/{OLD}/merge", json={}).status_code == 422
    assert client.get(f"/api/admin/principals/{OLD}/merge-preview").status_code == 422


def test_merge_permission_is_in_no_oauth_scope() -> None:
    from app.modules.auth.oauth import SCOPES
    from app.shared.permissions import PERMISSION_CATALOGUE

    assert "admin.users.merge" in PERMISSION_CATALOGUE
    assert all("admin.users.merge" not in perms for perms in SCOPES.values())
    # Also never through a future scope: the permission is forbidden for every token.
    from app.modules.auth.oauth import FORBIDDEN_PERMISSIONS, scope_permissions

    assert "admin.users.merge" in FORBIDDEN_PERMISSIONS
    assert "admin.users.merge" not in scope_permissions(list(SCOPES))


# -- Erased accounts, inactive target, privileges, retry --------------------------------


async def test_merge_into_a_deactivated_target_is_refused() -> None:
    target = _Row(NEW, "new")
    target.active = False
    with pytest.raises(ConflictError) as exc:
        await _svc(_Session([_Row(OLD, "old"), target])).preview(OLD, NEW, actor="admin")
    assert exc.value.code == "merge_target_inactive"


class _CountQueue(_Session):
    """`scalar` answers the queued counts in order."""

    def __init__(self, counts: list[int]) -> None:
        super().__init__(_pair())
        self.counts = list(counts)

    async def scalar(self, stmt: Any) -> int:
        self.statements.append(stmt)
        return self.counts.pop(0)


@pytest.mark.real_rules
@pytest.mark.parametrize(("counts", "erased"), [([1], True), ([0, 1], True), ([0, 0], False)])
async def test_erased_reads_requests_then_audit(counts: list[int], erased: bool) -> None:
    session = _CountQueue(counts)
    assert await _svc(session)._erased([OLD, NEW]) is erased
    assert "erasure_request" in str(session.statements[0])
    if len(counts) == 2:
        assert "audit_entry" in str(session.statements[1])


@pytest.mark.real_rules
async def test_erased_account_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    async def erased(_self: object, _ids: object) -> bool:
        return True

    monkeypatch.setattr(PrincipalMergeService, "_erased", erased)
    session = _Session(_pair())
    with pytest.raises(ConflictError) as exc:
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert exc.value.code == "principal_erased"
    assert session.dml == 0
    assert session.rolled_back == 1


class _GremiumRows(_Session):
    """`execute` answers the gremium rows (or names) queued for SELECT statements."""

    def __init__(self, rows: list[list[tuple[Any, ...]]], actor: object = None) -> None:
        super().__init__(_pair())
        self.rows = list(rows)
        self.actor = actor

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self.rows.pop(0) if self.rows else [])

    async def scalar(self, stmt: Any) -> Any:
        self.statements.append(stmt)
        return self.actor


@pytest.mark.real_rules
async def test_effective_rights(monkeypatch: pytest.MonkeyPatch) -> None:
    gid = uuid4()

    async def resolve(_db: object, row: _Row, _now: object) -> Principal:
        if row.sub == "boss":
            return Principal(sub="boss", roles=["admin"])
        return Principal(sub=row.sub, permissions={"budget.view"})

    monkeypatch.setattr(merge_mod, "resolve_principal", resolve)
    svc = _svc(_GremiumRows([[(gid, ["vote.cast", "session.manage"]), (uuid4(), None)]]))
    now = datetime.now(UTC)
    assert await svc._effective(None, now) == frozenset()
    assert await svc._effective(_any(_Row(OLD, "boss")), now) == frozenset({"*"})
    assert await svc._effective(_any(_Row(OLD, "old")), now) == frozenset(
        {"budget.view", f"vote.cast@{gid}", f"session.manage@{gid}"}
    )


def _rights(by_sub: dict[str | None, set[str]]) -> Any:
    async def effective(_self: object, row: _Row | None, _now: object) -> frozenset[str]:
        return frozenset(by_sub[row.sub if row is not None else None])

    return effective


@pytest.mark.real_rules
async def test_privileges_extra_rights_and_actor_cover(monkeypatch: pytest.MonkeyPatch) -> None:
    gid = uuid4()
    source, target = (_any(r) for r in _pair())
    # The target is admin: nothing is extra.
    monkeypatch.setattr(PrincipalMergeService, "_effective", _rights({"old": {"*"}, "new": {"*"}}))
    assert await _svc(_GremiumRows([]))._privileges(source, target, "x") == ([], True)
    # Same rights: nothing is extra, the actor is not read.
    monkeypatch.setattr(
        PrincipalMergeService, "_effective", _rights({"old": {"a"}, "new": {"a", "b"}})
    )
    assert await _svc(_GremiumRows([]))._privileges(source, target, "x") == ([], True)
    # The source is admin and holds a gremium right; the actor holds neither.
    monkeypatch.setattr(
        PrincipalMergeService,
        "_effective",
        _rights({"old": {"*", f"vote.manage@{gid}"}, "new": set(), "act": {"b"}}),
    )
    session = _GremiumRows([[(gid, "StuPa")]], actor=_Row(uuid4(), "act"))
    extra, covered = await _svc(session)._privileges(source, target, "act")
    assert covered is False
    assert [(p.key, p.gremium) for p in extra] == [("admin", None), ("vote.manage", "StuPa")]
    # An actor with the admin role covers everything; a global extra right needs no
    # gremium lookup.
    monkeypatch.setattr(
        PrincipalMergeService,
        "_effective",
        _rights({"old": {"budget.book"}, "new": set(), "act": {"*"}}),
    )
    extra, covered = await _svc(_GremiumRows([], actor=_Row(uuid4(), "act")))._privileges(
        source, target, "act"
    )
    assert covered is True
    assert [p.key for p in extra] == ["budget.book"]
    # An actor that holds exactly the extra rights covers them too.
    monkeypatch.setattr(
        PrincipalMergeService,
        "_effective",
        _rights({"old": {"budget.book"}, "new": set(), "act": {"budget.book"}}),
    )
    _, covered = await _svc(_GremiumRows([], actor=_Row(uuid4(), "act")))._privileges(
        source, target, "act"
    )
    assert covered is True


@pytest.mark.real_rules
async def test_preview_and_merge_refuse_uncovered_rights(
    monkeypatch: pytest.MonkeyPatch, recorded: list[dict[str, Any]]
) -> None:
    async def not_erased(_self: object, _ids: object) -> bool:
        return False

    async def extra(_self: object, *_a: object) -> tuple[list[MergePermissionOut], bool]:
        rights = [
            MergePermissionOut(key="admin"),
            MergePermissionOut(key="vote.cast", gremium="StuPa"),
        ]
        return rights, False

    monkeypatch.setattr(PrincipalMergeService, "_erased", not_erased)
    monkeypatch.setattr(PrincipalMergeService, "_privileges", extra)
    out = await _svc(_Session(_pair())).preview(OLD, NEW, actor="admin")
    assert out.can_merge is False
    assert out.actor_holds_extra is False
    assert [p.key for p in out.extra_permissions] == ["admin", "vote.cast"]
    session = _Session(_pair())
    with pytest.raises(ConflictError) as exc:
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert exc.value.code == "merge_privileges"
    assert exc.value.errors is not None
    assert [e.msg for e in exc.value.errors] == ["admin", "vote.cast (StuPa)"]
    assert session.dml == 0
    assert recorded == []


@pytest.mark.real_rules
async def test_merge_with_covered_extra_rights_records_them(
    monkeypatch: pytest.MonkeyPatch, recorded: list[dict[str, Any]]
) -> None:
    async def not_erased(_self: object, _ids: object) -> bool:
        return False

    async def extra(_self: object, *_a: object) -> tuple[list[MergePermissionOut], bool]:
        return [MergePermissionOut(key="budget.book")], True

    monkeypatch.setattr(PrincipalMergeService, "_erased", not_erased)
    monkeypatch.setattr(PrincipalMergeService, "_privileges", extra)
    await _svc(_Session(_pair())).merge(OLD, NEW, actor="admin")
    assert recorded[0]["data"]["extraPermissions"] == ["budget.book"]


class _PgError(Exception):
    def __init__(self, pgcode: str | None = None, sqlstate: str | None = None) -> None:
        super().__init__("db")
        self.pgcode = pgcode
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    "orig",
    [_PgError(pgcode="40P01"), _PgError(sqlstate="40001")],
)
async def test_deadlock_and_serialization_give_merge_retry(
    orig: _PgError, recorded: list[dict[str, Any]]
) -> None:
    session = _Session(_pair(), fail_on=1, fail_with=DBAPIError("UPDATE", {}, orig))
    with pytest.raises(ConflictError) as exc:
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert exc.value.code == "merge_retry"
    assert session.rolled_back == 1


async def test_a_wrapped_sqlstate_is_found_too(recorded: list[dict[str, Any]]) -> None:
    wrapper = _PgError()
    wrapper.__cause__ = _PgError(sqlstate="40P01")
    session = _Session(_pair(), fail_on=1, fail_with=DBAPIError("UPDATE", {}, wrapper))
    with pytest.raises(ConflictError) as exc:
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert exc.value.code == "merge_retry"


async def test_another_db_error_is_not_masked(recorded: list[dict[str, Any]]) -> None:
    session = _Session(_pair(), fail_on=1, fail_with=DBAPIError("UPDATE", {}, _PgError("XX000")))
    with pytest.raises(DBAPIError):
        await _svc(session).merge(OLD, NEW, actor="admin")
    assert session.rolled_back == 1
    no_code = _Session(_pair(), fail_on=1, fail_with=DBAPIError("UPDATE", {}, _PgError()))
    with pytest.raises(DBAPIError):
        await _svc(no_code).merge(OLD, NEW, actor="admin")
