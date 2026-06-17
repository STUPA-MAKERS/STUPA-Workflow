"""Branch-vollständige Unit-Suite (CI-Gate) für drei kritische Module ohne DB:

* ``app.modules.deadlines.service``  — Policy-CRUD, ``resolve_due_at``, ``transition_ref``,
  Scans/Locks/Marker.
* ``app.modules.deadlines.router``   — Admin-CRUD der Policy-Registry (real verdrahtet
  über einen Fake-``get_session``, sodass ``get_service`` + der echte Service mitlaufen).
* ``app.modules.flow.context``       — Guard-Kontext-Aufbau (``build_context`` + Helfer).

Alle Tests sind deterministisch (Ergebnis-Queue-Fake, keine Docker/Redis/Postgres)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.deadlines.models import DeadlinePolicy
from app.modules.deadlines.service import (
    DeadlinePolicyError,
    DeadlinePolicyService,
    DeadlineService,
    resolve_due_at,
    transition_ref,
)
from app.modules.flow import context as flow_context
from app.modules.flow.context import (
    _budget_fits,
    _committees_for_sub,
    _compare_type,
    _field_types,
    build_context,
)
from app.shared.guards import GuardContext
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
LEAD = timedelta(hours=24)


# =========================================================================== #
# service.py — transition_ref (alle Zweige)
# =========================================================================== #
def test_transition_ref_camel_and_snake_and_hex() -> None:
    tid = uuid4()
    assert transition_ref({"transitionId": str(tid)}) == tid
    assert transition_ref({"transition_id": str(tid)}) == tid
    # Bereits-UUID-Hex-String wird akzeptiert.
    assert transition_ref({"transitionId": UUID(str(tid)).hex}) == tid


@pytest.mark.parametrize(
    "value",
    [None, {}, {"foo": "bar"}, {"transitionId": "not-a-uuid"}, {"transitionId": 123}],
)
def test_transition_ref_invalid_is_none(value: Any) -> None:
    assert transition_ref(value) is None


# =========================================================================== #
# service.py — resolve_due_at (jede kind-Verzweigung + fehlende Bezugswerte)
# =========================================================================== #
def _policy(kind: str, **kw: object) -> DeadlinePolicy:
    return DeadlinePolicy(key="k", label={"de": "X"}, kind=kind, **kw)


def test_resolve_absolute() -> None:
    assert resolve_due_at(_policy("absolute", absolute_at=NOW)) == NOW


def test_resolve_relative_submitted_with_and_without_ref() -> None:
    p = _policy("relative_submitted", offset_days=14)
    assert resolve_due_at(p, submitted_at=NOW) == NOW + timedelta(days=14)
    assert resolve_due_at(p, submitted_at=None) is None


def test_resolve_relative_changed_with_and_without_ref() -> None:
    p = _policy("relative_changed", offset_days=7)
    assert resolve_due_at(p, changed_at=NOW) == NOW + timedelta(days=7)
    assert resolve_due_at(p, changed_at=None) is None


def test_resolve_offset_days_none_defaults_to_zero() -> None:
    # offset_days=None → days=0 (``offset_days or 0``).
    p = _policy("relative_submitted", offset_days=None)
    assert resolve_due_at(p, submitted_at=NOW) == NOW


def test_resolve_unknown_kind_is_none() -> None:
    assert resolve_due_at(_policy("bogus")) is None


# =========================================================================== #
# service.py — DeadlineService Scans/Locks/Create/Marker
# =========================================================================== #
async def test_due_action_deadline_ids() -> None:
    ids = [uuid4(), uuid4()]
    svc = DeadlineService(fake_session(result(*ids)))
    assert await svc.due_action_deadline_ids(NOW) == ids


async def test_due_reminder_ids() -> None:
    ids = [uuid4()]
    svc = DeadlineService(fake_session(result(*ids)))
    assert await svc.due_reminder_ids(NOW, LEAD) == ids


async def test_due_open_vote_ids() -> None:
    ids = [uuid4()]
    svc = DeadlineService(fake_session(result(*ids)))
    assert await svc.due_open_vote_ids(NOW) == ids


async def test_lock_action_deadline_hit_and_miss() -> None:
    deadline = SimpleNamespace(id=uuid4())
    assert await DeadlineService(fake_session(result(deadline))).lock_action_deadline(
        deadline.id, NOW
    ) is deadline
    assert await DeadlineService(fake_session(result())).lock_action_deadline(uuid4(), NOW) is None


async def test_lock_reminder_hit_and_miss() -> None:
    deadline = SimpleNamespace(id=uuid4())
    assert await DeadlineService(fake_session(result(deadline))).lock_reminder(
        deadline.id, NOW, LEAD
    ) is deadline
    assert await DeadlineService(fake_session(result())).lock_reminder(uuid4(), NOW, LEAD) is None


async def test_lock_open_vote_hit_and_miss() -> None:
    vote = SimpleNamespace(id=uuid4())
    assert await DeadlineService(fake_session(result(vote))).lock_open_vote(vote.id, NOW) is vote
    assert await DeadlineService(fake_session(result())).lock_open_vote(uuid4(), NOW) is None


async def test_create_persists_and_commits() -> None:
    session = fake_session()
    svc = DeadlineService(session)
    tid = uuid4()
    deadline = await svc.create(
        kind="requeue",
        due_at=NOW,
        application_id=uuid4(),
        type_id=uuid4(),
        action_on_pass={"transitionId": str(tid)},
    )
    assert deadline.kind == "requeue"
    assert session.flushed == 1
    assert session.committed == 1
    assert deadline in session.added


async def test_consume_action_clears_and_commits() -> None:
    session = fake_session()
    deadline = SimpleNamespace(action_on_pass={"transitionId": str(uuid4())})
    await DeadlineService(session).consume_action(cast("Any", deadline))
    assert deadline.action_on_pass is None
    assert session.committed == 1


async def test_mark_reminded_sets_timestamp_and_commits() -> None:
    session = fake_session()
    deadline = SimpleNamespace(reminded_at=None)
    await DeadlineService(session).mark_reminded(cast("Any", deadline), NOW)
    assert deadline.reminded_at == NOW
    assert session.committed == 1


# =========================================================================== #
# service.py — DeadlinePolicyService (direkte Unit-Aufrufe, alle Branches)
# =========================================================================== #
async def test_policy_list_returns_rows() -> None:
    p = _policy("absolute", absolute_at=NOW)
    rows = await DeadlinePolicyService(fake_session(result(p))).list()
    assert rows == [p]


async def test_policy_get_uses_session_get() -> None:
    p = _policy("absolute", absolute_at=NOW)
    session = fake_session()
    session.get_results.append(p)
    assert await DeadlinePolicyService(session).get(uuid4()) is p


async def test_policy_get_by_key_hit_and_miss() -> None:
    p = _policy("absolute", absolute_at=NOW)
    assert await DeadlinePolicyService(fake_session(result(p))).get_by_key("k") is p
    assert await DeadlinePolicyService(fake_session(result())).get_by_key("k") is None


async def test_policy_create_absolute_keeps_only_absolute_at() -> None:
    # get_by_key → None (frei), dann add/flush/commit/refresh.
    session = fake_session(result())
    created = await DeadlinePolicyService(session).create(
        key="sem",
        label={"de": "S"},
        kind="absolute",
        absolute_at=NOW,
        offset_days=99,  # bei absolute verworfen → None
    )
    assert created.absolute_at == NOW
    assert created.offset_days is None
    assert session.committed == 1


async def test_policy_create_relative_keeps_only_offset_days() -> None:
    session = fake_session(result())
    created = await DeadlinePolicyService(session).create(
        key="rel",
        label={"de": "R"},
        kind="relative_submitted",
        absolute_at=NOW,  # bei relativ verworfen → None
        offset_days=14,
    )
    assert created.offset_days == 14
    assert created.absolute_at is None


async def test_policy_create_duplicate_key_raises() -> None:
    existing = _policy("absolute", absolute_at=NOW)
    session = fake_session(result(existing))  # get_by_key trifft
    with pytest.raises(DeadlinePolicyError, match="already exists"):
        await DeadlinePolicyService(session).create(
            key="k", label={"de": "X"}, kind="absolute", absolute_at=NOW, offset_days=None
        )
    assert session.committed == 0


async def test_policy_update_absolute_with_new_value() -> None:
    # kind→absolute (neuer kind), absolute_at gesetzt → übernommen, offset_days geleert.
    policy = _policy("relative_submitted", offset_days=5)
    later = NOW + timedelta(days=1)
    out = await DeadlinePolicyService(fake_session()).update(
        policy, label={"de": "Neu"}, kind="absolute", absolute_at=later, offset_days=None
    )
    assert out.label == {"de": "Neu"}
    assert out.kind == "absolute"
    assert out.absolute_at == later
    assert out.offset_days is None


async def test_policy_update_absolute_without_new_value_keeps_old() -> None:
    # effective_kind aus policy (kind=None), absolute_at=None → alter Wert bleibt; offset geleert.
    policy = _policy("absolute", absolute_at=NOW, offset_days=3)
    out = await DeadlinePolicyService(fake_session()).update(policy)
    assert out.absolute_at == NOW
    assert out.offset_days is None
    assert out.label == {"de": "X"}  # label None → unverändert
    assert out.kind == "absolute"  # kind None → unverändert


async def test_policy_update_relative_with_new_offset() -> None:
    policy = _policy("absolute", absolute_at=NOW)
    out = await DeadlinePolicyService(fake_session()).update(
        policy, kind="relative_changed", offset_days=21
    )
    assert out.kind == "relative_changed"
    assert out.offset_days == 21
    assert out.absolute_at is None


async def test_policy_update_relative_without_new_offset_keeps_old() -> None:
    # effective_kind relativ aus policy, offset_days=None → alter offset bleibt; absolute geleert.
    policy = _policy("relative_submitted", offset_days=8, absolute_at=NOW)
    out = await DeadlinePolicyService(fake_session()).update(policy)
    assert out.offset_days == 8
    assert out.absolute_at is None


async def test_policy_delete_removes_and_commits() -> None:
    session = fake_session()
    policy = _policy("absolute", absolute_at=NOW)
    await DeadlinePolicyService(session).delete(policy)
    assert policy in session.deleted
    assert session.committed == 1


# =========================================================================== #
# router.py — voll verdrahtet über echten Service (Fake-get_session)
# =========================================================================== #
class _RouterFakeSession:
    """Minimaler AsyncSession-Stub für die Router-Tests: bedient genau die
    ``DeadlinePolicyService``-Aufrufe der jeweiligen Route."""

    def __init__(self, *, execute_results: list[Any] | None = None) -> None:
        self._execute = list(execute_results or [])
        self.get_obj: Any = None
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = 0

    async def execute(self, _stmt: Any) -> Any:
        return self._execute.pop(0)

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self.get_obj

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None: ...

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, _obj: Any) -> None: ...


def _make_app(session: _RouterFakeSession) -> FastAPI:
    application = create_app()

    async def _override() -> AsyncGenerator[Any]:
        yield session

    application.dependency_overrides[get_session] = _override
    return application


def _as_admin(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions={"admin.deadlines"}
    )


def _as_flow_editor(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="f", permissions={"flow.configure"}
    )


def _as_nobody(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="u", permissions=set()
    )


def test_router_list_ok_runs_real_service() -> None:
    policy = _policy("absolute", absolute_at=NOW)
    policy.id = uuid4()
    session = _RouterFakeSession(execute_results=[result(policy)])
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).get("/api/admin/deadline-policies")
    assert res.status_code == 200
    assert res.json()[0]["key"] == "k"


def test_router_list_readable_by_flow_configure() -> None:
    session = _RouterFakeSession(execute_results=[result()])
    app = _make_app(session)
    _as_flow_editor(app)
    assert TestClient(app).get("/api/admin/deadline-policies").status_code == 200


def test_router_list_forbidden_without_perm() -> None:
    session = _RouterFakeSession(execute_results=[result()])
    app = _make_app(session)
    _as_nobody(app)
    assert TestClient(app).get("/api/admin/deadline-policies").status_code == 403


def test_router_create_ok_runs_real_service() -> None:
    # get_by_key → leeres execute-Ergebnis (frei), dann add/flush/commit/refresh.
    session = _RouterFakeSession(execute_results=[result()])
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).post(
        "/api/admin/deadline-policies",
        json={
            "key": "edit_window",
            "label": {"de": "Frist"},
            "kind": "relative_changed",
            "offsetDays": 7,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["kind"] == "relative_changed"
    assert body["offsetDays"] == 7
    assert session.committed == 1


def test_router_create_duplicate_key_conflict_409() -> None:
    existing = _policy("absolute", absolute_at=NOW)
    existing.id = uuid4()
    session = _RouterFakeSession(execute_results=[result(existing)])  # get_by_key trifft
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).post(
        "/api/admin/deadline-policies",
        json={"key": "k", "label": {"de": "X"}, "kind": "absolute", "absoluteAt": NOW.isoformat()},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "deadline_policy_key"


def test_router_create_forbidden_for_flow_editor() -> None:
    # Schreiben bleibt admin.deadlines — flow.configure darf NICHT erstellen.
    session = _RouterFakeSession(execute_results=[result()])
    app = _make_app(session)
    _as_flow_editor(app)
    res = TestClient(app).post(
        "/api/admin/deadline-policies",
        json={"key": "x", "label": {"de": "X"}, "kind": "absolute", "absoluteAt": NOW.isoformat()},
    )
    assert res.status_code == 403


def test_router_update_ok_runs_real_service() -> None:
    policy = _policy("relative_submitted", offset_days=5)
    policy.id = uuid4()
    session = _RouterFakeSession()
    session.get_obj = policy
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).patch(
        f"/api/admin/deadline-policies/{policy.id}",
        json={"kind": "absolute", "absoluteAt": NOW.isoformat()},
    )
    assert res.status_code == 200
    assert res.json()["kind"] == "absolute"
    assert session.committed == 1


def test_router_update_not_found_404() -> None:
    session = _RouterFakeSession()
    session.get_obj = None  # service.get → None
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).patch(
        f"/api/admin/deadline-policies/{uuid4()}",
        json={"label": {"de": "Neu"}},
    )
    assert res.status_code == 404


def test_router_delete_ok_runs_real_service() -> None:
    policy = _policy("absolute", absolute_at=NOW)
    policy.id = uuid4()
    session = _RouterFakeSession()
    session.get_obj = policy
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).delete(f"/api/admin/deadline-policies/{policy.id}")
    assert res.status_code == 204
    assert policy in session.deleted
    assert session.committed == 1


def test_router_delete_not_found_404() -> None:
    session = _RouterFakeSession()
    session.get_obj = None
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).delete(f"/api/admin/deadline-policies/{uuid4()}")
    assert res.status_code == 404


# =========================================================================== #
# context.py — _compare_type
# =========================================================================== #
@pytest.mark.parametrize(
    ("field_type", "expected"),
    [
        ("number", "number"),
        ("currency", "currency"),
        ("date", "date"),
        ("checkbox", "bool"),
        ("boolean", "bool"),
        ("text", "text"),  # Default
        ("freitext-unknown", "text"),  # unbekannt → Default
    ],
)
def test_compare_type_mapping(field_type: str, expected: str) -> None:
    assert _compare_type(field_type) == expected


# =========================================================================== #
# context.py — _committees_for_sub
# =========================================================================== #
async def test_committees_for_sub_empty_sub_short_circuits() -> None:
    # not sub → frozenset() ohne DB-Zugriff.
    session = fake_session()
    assert await _committees_for_sub(session, None) == frozenset()
    assert await _committees_for_sub(session, "") == frozenset()
    assert session.statements == []  # kein execute


async def test_committees_for_sub_maps_rows_to_str() -> None:
    g1, g2 = uuid4(), uuid4()
    session = fake_session(result(g1, g2))
    out = await _committees_for_sub(session, "sub-1")
    assert out == frozenset({str(g1), str(g2)})


# =========================================================================== #
# context.py — _budget_fits (fail-closed + voller Pfad, beide Seiten)
# =========================================================================== #
def _app_for_budget(*, budget_id: Any, fiscal: Any, amount: Any) -> SimpleNamespace:
    return SimpleNamespace(budget_id=budget_id, fiscal_year_id=fiscal, amount=amount)


async def test_budget_fits_fail_closed_when_budget_missing() -> None:
    session = fake_session()
    app = _app_for_budget(budget_id=None, fiscal=uuid4(), amount=Decimal("10"))
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_fail_closed_when_fiscal_missing() -> None:
    session = fake_session()
    app = _app_for_budget(budget_id=uuid4(), fiscal=None, amount=Decimal("10"))
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_fail_closed_when_amount_missing() -> None:
    session = fake_session()
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=None)
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_true_when_amount_within_available() -> None:
    session = fake_session()
    # scalar-Queue: (1) allocated, (2) flow.
    session.scalar_results = [Decimal("100"), Decimal("-20")]  # available = 80
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("80"))
    assert await _budget_fits(session, cast("Any", app)) is True


async def test_budget_fits_false_when_amount_exceeds_available() -> None:
    session = fake_session()
    session.scalar_results = [Decimal("100"), Decimal("-20")]  # available = 80
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("80.01"))
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_handles_none_allocated_and_flow() -> None:
    # allocated None → Decimal("0"); flow None → Decimal("0"); available = 0.
    session = fake_session()  # scalar_results leer → beide None
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("0"))
    assert await _budget_fits(session, cast("Any", app)) is True  # 0 <= 0
    session2 = fake_session()
    app2 = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("0.01"))
    assert await _budget_fits(session2, cast("Any", app2)) is False  # 0.01 <= 0 → False


# =========================================================================== #
# context.py — _field_types
# =========================================================================== #
async def test_field_types_maps_and_adds_amount() -> None:
    rows = [("betrag", "currency"), ("titel", "text"), ("anzahl", "number"), ("ok", "checkbox")]
    session = fake_session(result(*rows))
    app = SimpleNamespace(form_version_id=uuid4())
    out = await _field_types(session, cast("Any", app))
    assert out == {
        "betrag": "currency",
        "titel": "text",
        "anzahl": "number",
        "ok": "bool",
        "amount": "currency",  # Built-in immer ergänzt
    }


# =========================================================================== #
# context.py — build_context (beide Seiten jedes if)
# =========================================================================== #
def _ctx_app(
    *,
    data: Any,
    created_by: str | None,
    budget_id: Any = None,
    amount: Any = Decimal("5"),
    fiscal: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        data=data,
        created_by=created_by,
        budget_id=budget_id,
        fiscal_year_id=fiscal,
        amount=amount,
        form_version_id=uuid4(),
    )


def _principal(**over: object) -> Principal:
    base: dict[str, object] = {"sub": "actor-1", "roles": ["chair"], "permissions": set()}
    base.update(over)
    return Principal(**base)  # type: ignore[arg-type]


@pytest.fixture
def _no_committees(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_committees_for_sub`` ohne DB: liefert deterministisch frozenset()."""

    async def _cs(_session: object, _sub: str | None) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr(flow_context, "_committees_for_sub", _cs)


@pytest.fixture
def _no_field_types(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ft(_session: object, _app: object) -> dict[str, str]:
        return {"amount": "currency"}

    monkeypatch.setattr(flow_context, "_field_types", _ft)


@pytest.fixture
def _budget_no_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _bf(_session: object, _app: object) -> bool:
        return False

    monkeypatch.setattr(flow_context, "_budget_fits", _bf)


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_actor_is_creator() -> None:
    # manual=True, created_by==principal.sub → actor_is_applicant True; roles aus principal.
    app = _ctx_app(
        data={"_applicantRoles": ["member"], "feld": 1},
        created_by="actor-1",
        budget_id=uuid4(),
    )
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert isinstance(ctx, GuardContext)
    assert ctx.manual is True
    assert ctx.actor_is_applicant is True
    assert ctx.roles == frozenset({"chair"})
    assert ctx.applicant_roles == frozenset({"member"})
    assert ctx.budget_id == str(app.budget_id)
    assert ctx.field_values["amount"] == app.amount
    assert ctx.field_values["feld"] == 1
    assert ctx.budget_fits is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_as_applicant_magic_link() -> None:
    # as_applicant=True, created_by != sub → actor_is_applicant True über Magic-Link.
    app = _ctx_app(data={}, created_by="someone-else")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True, as_applicant=True
    )
    assert ctx.actor_is_applicant is True


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_not_applicant() -> None:
    # manual=True, kein Magic-Link, created_by != sub → actor_is_applicant False.
    app = _ctx_app(data={}, created_by="someone-else")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.actor_is_applicant is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_created_by_none() -> None:
    # created_by None → die created_by-Klausel ist False → actor_is_applicant False.
    app = _ctx_app(data={}, created_by=None)
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.actor_is_applicant is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_automatic_strips_actor_signals() -> None:
    # manual=False → roles + actor_committees leer; actor_is_applicant False (manual-Gate).
    app = _ctx_app(data={"_applicantRoles": ["x"]}, created_by="actor-1", budget_id=None)
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=False, as_applicant=True
    )
    assert ctx.manual is False
    assert ctx.roles == frozenset()
    assert ctx.actor_committees == frozenset()
    assert ctx.actor_is_applicant is False  # manual=False blockt
    assert ctx.budget_id is None  # budget_id None → None


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_data_not_dict_and_roles_not_list() -> None:
    # app.data ist KEIN dict → field_values startet leer; raw_roles None → applicant_roles leer.
    app = _ctx_app(data=None, created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.applicant_roles == frozenset()
    assert ctx.field_values == {"amount": app.amount}


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_applicant_roles_present_but_not_list() -> None:
    # _applicantRoles vorhanden, aber kein list → applicant_roles leer (isinstance-False-Zweig).
    app = _ctx_app(data={"_applicantRoles": "not-a-list"}, created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.applicant_roles == frozenset()


@pytest.mark.usefixtures("_no_field_types", "_budget_no_fit")
async def test_build_context_deadline_passed_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _cs(_session: object, _sub: str | None) -> frozenset[str]:
        return frozenset({"g-1"})

    monkeypatch.setattr(flow_context, "_committees_for_sub", _cs)
    app = _ctx_app(data={}, created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True, deadline_passed=True
    )
    assert ctx.deadline_passed is True
    assert ctx.actor_committees == frozenset({"g-1"})
    assert ctx.applicant_committees == frozenset({"g-1"})
