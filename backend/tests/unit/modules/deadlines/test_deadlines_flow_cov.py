"""Branch-complete unit suite (CI gate) for three critical modules, without a DB.

It covers:

* `app.modules.deadlines.service` — policy CRUD, `resolve_due_at`, `transition_ref`,
  scans, locks and markers.
* `app.modules.deadlines.router` — admin CRUD of the policy registry. A fake
  `get_session` wires the route for real, so `get_service` and the real service run.
* `app.modules.flow.context` — guard context assembly (`build_context` and helpers).

Every test is deterministic. The result-queue fake needs no Docker, Redis or Postgres.
"""

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


# Tests of app.modules.deadlines.service.
def test_transition_ref_camel_and_snake_and_hex() -> None:
    tid = uuid4()
    assert transition_ref({"transitionId": str(tid)}) == tid
    assert transition_ref({"transition_id": str(tid)}) == tid
    # The parser also accepts a plain UUID hex string.
    assert transition_ref({"transitionId": UUID(str(tid)).hex}) == tid


@pytest.mark.parametrize(
    "value",
    [None, {}, {"foo": "bar"}, {"transitionId": "not-a-uuid"}, {"transitionId": 123}],
)
def test_transition_ref_invalid_is_none(value: Any) -> None:
    assert transition_ref(value) is None


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
    # An offset_days of None gives days=0 through `offset_days or 0`.
    p = _policy("relative_submitted", offset_days=None)
    assert resolve_due_at(p, submitted_at=NOW) == NOW


def test_resolve_unknown_kind_is_none() -> None:
    assert resolve_due_at(_policy("bogus")) is None


def test_resolve_absolute_without_date_is_none() -> None:
    assert resolve_due_at(_policy("absolute", absolute_at=None)) is None


_JUN = datetime(2026, 6, 9, 0, 0, tzinfo=UTC)  # Berlin summer time (UTC+2)
_JAN = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)  # Berlin winter time (UTC+1)


def test_resolve_absolute_snaps_to_at_time_summer() -> None:
    p = _policy("absolute", absolute_at=_JUN, at_time="23:59", timezone="Europe/Berlin")
    assert resolve_due_at(p) == datetime(2026, 6, 9, 21, 59, tzinfo=UTC)


def test_resolve_absolute_snaps_to_at_time_winter_dst() -> None:
    # The same at_time with a different UTC offset (CET vs CEST) proves the DST handling.
    p = _policy("absolute", absolute_at=_JAN, at_time="23:59", timezone="Europe/Berlin")
    assert resolve_due_at(p) == datetime(2026, 1, 15, 22, 59, tzinfo=UTC)


def test_resolve_relative_snaps_to_at_time() -> None:
    submitted = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    p = _policy("relative_submitted", offset_days=14, at_time="23:59", timezone="Europe/Berlin")
    assert resolve_due_at(p, submitted_at=submitted) == datetime(2026, 6, 15, 21, 59, tzinfo=UTC)


def test_resolve_malformed_at_time_falls_back_to_raw() -> None:
    for bad in ("nope", "25:00", "12:60"):
        p = _policy("absolute", absolute_at=_JUN, at_time=bad, timezone="Europe/Berlin")
        assert resolve_due_at(p) == _JUN


def test_resolve_unknown_timezone_falls_back_to_local_default() -> None:
    # An invalid tz makes _zone use the configured local default (Europe/Berlin).
    p = _policy("absolute", absolute_at=_JUN, at_time="12:00", timezone="Bogus/Zone")
    assert resolve_due_at(p) == datetime(2026, 6, 9, 10, 0, tzinfo=UTC)


def test_resolve_none_timezone_uses_local_default() -> None:
    p = _policy("absolute", absolute_at=_JUN, at_time="12:00", timezone=None)
    assert resolve_due_at(p) == datetime(2026, 6, 9, 10, 0, tzinfo=UTC)


def _recurring(dates: object, **kw: object) -> DeadlinePolicy:
    return _policy("recurring", dates=dates, **kw)


def test_resolve_recurring_picks_earliest_future_date() -> None:
    p = _recurring(
        ["2026-06-01", "2026-07-01", "2026-08-01"], at_time="23:59", timezone="Europe/Berlin"
    )
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert resolve_due_at(p, now=now) == datetime(2026, 7, 1, 21, 59, tzinfo=UTC)


def test_resolve_recurring_without_at_time_uses_local_midnight() -> None:
    p = _recurring(["2026-07-01"], timezone="Europe/Berlin")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    # 2026-07-01 00:00 Berlin (CEST, UTC+2) == 2026-06-30 22:00 UTC.
    assert resolve_due_at(p, now=now) == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)


def test_resolve_recurring_all_passed_is_none() -> None:
    p = _recurring(["2026-01-01", "2026-02-01"], timezone="Europe/Berlin")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert resolve_due_at(p, now=now) is None


def test_resolve_recurring_without_now_is_none() -> None:
    assert resolve_due_at(_recurring(["2026-07-01"])) is None


@pytest.mark.parametrize("dates", [None, [], "2026-07-01"])
def test_resolve_recurring_missing_or_empty_dates_is_none(dates: object) -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert resolve_due_at(_recurring(dates), now=now) is None


def test_resolve_recurring_skips_invalid_entries() -> None:
    p = _recurring(["not-a-date", 123, "2026-07-01"], timezone="Europe/Berlin")
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert resolve_due_at(p, now=now) == datetime(2026, 6, 30, 22, 0, tzinfo=UTC)


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
    # get_by_key returns None, so the key is free. Then come add, flush, commit and refresh.
    session = fake_session(result())
    created = await DeadlinePolicyService(session).create(
        key="sem",
        label={"de": "S"},
        kind="absolute",
        absolute_at=NOW,
        offset_days=99,  # dropped for an absolute policy, so None
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
        absolute_at=NOW,  # dropped for a relative policy, so None
        offset_days=14,
    )
    assert created.offset_days == 14
    assert created.absolute_at is None


async def test_policy_create_duplicate_key_raises() -> None:
    existing = _policy("absolute", absolute_at=NOW)
    session = fake_session(result(existing))  # get_by_key hits
    with pytest.raises(DeadlinePolicyError, match="already exists"):
        await DeadlinePolicyService(session).create(
            key="k", label={"de": "X"}, kind="absolute", absolute_at=NOW, offset_days=None
        )
    assert session.committed == 0


async def test_policy_update_absolute_with_new_value() -> None:
    # A new kind of absolute with absolute_at set keeps the date and clears offset_days.
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
    # effective_kind comes from the policy, because kind is None. With absolute_at None
    # the old date stays and the offset is cleared.
    policy = _policy("absolute", absolute_at=NOW, offset_days=3)
    out = await DeadlinePolicyService(fake_session()).update(policy)
    assert out.absolute_at == NOW
    assert out.offset_days is None
    assert out.label == {"de": "X"}  # label None leaves it unchanged
    assert out.kind == "absolute"  # kind None leaves it unchanged


async def test_policy_update_relative_with_new_offset() -> None:
    policy = _policy("absolute", absolute_at=NOW)
    out = await DeadlinePolicyService(fake_session()).update(
        policy, kind="relative_changed", offset_days=21
    )
    assert out.kind == "relative_changed"
    assert out.offset_days == 21
    assert out.absolute_at is None


async def test_policy_update_relative_without_new_offset_keeps_old() -> None:
    # effective_kind is relative and comes from the policy. With offset_days None the old
    # offset stays and absolute_at is cleared.
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


# Tests of app.modules.deadlines.router, wired to the real service.
class _RouterFakeSession:
    """Minimal AsyncSession stub for the router tests.

    It serves exactly the `DeadlinePolicyService` calls of the route under test.
    """

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
    # get_by_key gets an empty execute result, so the key is free. Then come add, flush,
    # commit and refresh.
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
    session = _RouterFakeSession(execute_results=[result(existing)])  # get_by_key hits
    app = _make_app(session)
    _as_admin(app)
    res = TestClient(app).post(
        "/api/admin/deadline-policies",
        json={"key": "k", "label": {"de": "X"}, "kind": "absolute", "absoluteAt": NOW.isoformat()},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "deadline_policy_key"


def test_router_create_forbidden_for_flow_editor() -> None:
    # A write still needs admin.deadlines. A holder of flow.configure cannot create.
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
    session.get_obj = None  # service.get returns None
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


# Tests of app.modules.flow.context.
@pytest.mark.parametrize(
    ("field_type", "expected"),
    [
        ("number", "number"),
        ("currency", "currency"),
        ("date", "date"),
        ("checkbox", "bool"),
        ("boolean", "bool"),
        ("text", "text"),  # default
        ("freitext-unknown", "text"),  # unknown maps to the default
    ],
)
def test_compare_type_mapping(field_type: str, expected: str) -> None:
    assert _compare_type(field_type) == expected


async def test_committees_for_sub_empty_sub_short_circuits() -> None:
    # A falsy sub returns frozenset() without a DB read.
    session = fake_session()
    assert await _committees_for_sub(session, None) == frozenset()
    assert await _committees_for_sub(session, "") == frozenset()
    assert session.statements == []  # no execute


async def test_committees_for_sub_maps_rows_to_str() -> None:
    g1, g2 = uuid4(), uuid4()
    session = fake_session(result(g1, g2))
    out = await _committees_for_sub(session, "sub-1")
    assert out == frozenset({str(g1), str(g2)})


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
    # scalar queue: the allocated sum, then the flow sum.
    session.scalar_results = [Decimal("100"), Decimal("-20")]  # available = 80
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("80"))
    assert await _budget_fits(session, cast("Any", app)) is True


async def test_budget_fits_false_when_amount_exceeds_available() -> None:
    session = fake_session()
    session.scalar_results = [Decimal("100"), Decimal("-20")]  # available = 80
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("80.01"))
    assert await _budget_fits(session, cast("Any", app)) is False


async def test_budget_fits_handles_none_allocated_and_flow() -> None:
    # An allocated of None and a flow of None both become Decimal("0"), so available is 0.
    session = fake_session()  # empty scalar_results, so both are None
    app = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("0"))
    assert await _budget_fits(session, cast("Any", app)) is True  # 0 <= 0
    session2 = fake_session()
    app2 = _app_for_budget(budget_id=uuid4(), fiscal=uuid4(), amount=Decimal("0.01"))
    assert await _budget_fits(session2, cast("Any", app2)) is False  # 0.01 <= 0 → False


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
        "amount": "currency",  # the built-in is always added
    }


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
        id=uuid4(),
        type_id=uuid4(),
    )


@pytest.fixture(autouse=True)
def _ctx_extras_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the context helpers `_application_type_key` and `_has_attachment`.

    The stubs keep the tests free of a DB. `test_flow_context` covers the real bodies.
    This fixture does nothing for the tests in this file that build no context.
    """

    async def _atk(_session: object, _app: object) -> str | None:
        return None

    async def _ha(_session: object, _app: object) -> bool:
        return False

    monkeypatch.setattr(flow_context, "_application_type_key", _atk)
    monkeypatch.setattr(flow_context, "_has_attachment", _ha)


def _principal(**over: object) -> Principal:
    base: dict[str, object] = {"sub": "actor-1", "roles": ["chair"], "permissions": set()}
    base.update(over)
    return Principal(**base)  # type: ignore[arg-type]


@pytest.fixture
def _no_committees(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `_committees_for_sub` return frozenset() without a DB."""

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
    # With manual=True and created_by == principal.sub, actor_is_applicant is True. The
    # roles come from the principal.
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
    # With as_applicant=True and created_by != sub, the magic link sets actor_is_applicant.
    app = _ctx_app(data={}, created_by="someone-else")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True, as_applicant=True
    )
    assert ctx.actor_is_applicant is True


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_not_applicant() -> None:
    # With manual=True, no magic link and created_by != sub, actor_is_applicant is False.
    app = _ctx_app(data={}, created_by="someone-else")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.actor_is_applicant is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_manual_created_by_none() -> None:
    # created_by None makes the created_by clause False, so actor_is_applicant is False.
    app = _ctx_app(data={}, created_by=None)
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.actor_is_applicant is False


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_automatic_strips_actor_signals() -> None:
    # With manual=False the roles and actor_committees stay empty. The manual gate also
    # makes actor_is_applicant False.
    app = _ctx_app(data={"_applicantRoles": ["x"]}, created_by="actor-1", budget_id=None)
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=False, as_applicant=True
    )
    assert ctx.manual is False
    assert ctx.roles == frozenset()
    assert ctx.actor_committees == frozenset()
    assert ctx.actor_is_applicant is False  # the manual gate blocks it
    assert ctx.budget_id is None  # budget_id None stays None


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_data_not_dict_and_roles_not_list() -> None:
    # app.data is not a dict, so field_values starts empty. A raw_roles of None leaves
    # applicant_roles empty.
    app = _ctx_app(data=None, created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True
    )
    assert ctx.applicant_roles == frozenset()
    assert ctx.field_values == {"amount": app.amount}


@pytest.mark.usefixtures("_no_committees", "_no_field_types", "_budget_no_fit")
async def test_build_context_applicant_roles_present_but_not_list() -> None:
    # _applicantRoles is present but is not a list, so applicant_roles stays empty. This
    # is the isinstance False branch.
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
