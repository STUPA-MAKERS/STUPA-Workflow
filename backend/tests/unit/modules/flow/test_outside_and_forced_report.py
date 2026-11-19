"""Unit tests of the outside decision, the forced-status report and their routes.

The integration suite covers the database paths. These tests cover the gates, the
pure parts and the branches that the database tests do not reach.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.applications.decision import (
    CODE_AMOUNT_REQUIRED,
    DecisionIn,
    amount_required,
    check_amount_given,
)
from app.modules.auth.principal import Principal
from app.modules.flow import forced_report as report_mod
from app.modules.flow import forced_router
from app.modules.flow import outside_decision as outside_mod
from app.modules.flow import router as flow_router
from app.modules.flow.forced_report import _Row, period, summarize
from app.modules.flow.outside_decision import OutsideDecisionIn, check_meeting_date
from app.modules.flow.router import get_flow_service
from app.modules.flow.schemas import TransitionResult
from app.modules.flow.service import FlowService, StagedFire
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem
from tests._support.flow_fakes import fake_session, result

TODAY = date(2026, 11, 19)


def _row(reason: str, from_key: str | None, to_key: str, *, days: int = 0) -> _Row:
    return _Row(
        application_id=uuid4(),
        title="T",
        at=datetime(2026, 11, 19, tzinfo=UTC) - timedelta(days=days),
        reason=reason,
        note=None,
        from_key=from_key,
        from_label={"de": from_key or ""},
        to_key=to_key,
        to_label={"de": to_key},
    )


def test_amount_required_only_when_entering_an_approval() -> None:
    """§ 001610: required on the way in, not between two approvals, not without amount."""
    one = Decimal("1.00")
    assert amount_required(entering=True, was_approved=False, requested=one) is True
    assert amount_required(entering=True, was_approved=True, requested=one) is False
    assert amount_required(entering=False, was_approved=False, requested=one) is False
    assert amount_required(entering=True, was_approved=False, requested=None) is False
    check_amount_given(False, None)
    check_amount_given(True, DecisionIn(approvedAmount=one))
    for missing in (None, DecisionIn()):
        with pytest.raises(ValidationProblem) as err:
            check_amount_given(True, missing)
        assert err.value.code == CODE_AMOUNT_REQUIRED


def test_period_defaults_and_refuses_a_reversed_range() -> None:
    assert period(None, None, TODAY) == (TODAY - timedelta(days=90), TODAY)
    assert period(date(2026, 1, 1), date(2026, 2, 1), TODAY) == (date(2026, 1, 1), date(2026, 2, 1))
    with pytest.raises(ValidationProblem):
        period(date(2026, 3, 1), date(2026, 2, 1), TODAY)


def test_summarize_sorts_the_largest_count_first() -> None:
    rows = [
        _row("other", "a", "b"),
        _row("none", None, "b"),
        _row("other", "a", "b", days=1),
        _row("applicant_error", "a", "c"),
    ]
    out = summarize(rows, TODAY, TODAY)
    assert out.total == 4
    assert [(r.reason, r.count) for r in out.by_reason] == [
        ("other", 2),
        ("applicant_error", 1),
        ("none", 1),
    ]
    assert [(p.from_key, p.to_key, p.count) for p in out.by_path] == [
        ("a", "b", 2),
        (None, "b", 1),
        ("a", "c", 1),
    ]
    assert out.model_dump(by_alias=True)["from"] == TODAY


def test_title_reads_a_text_only() -> None:
    assert report_mod._title({"title": "  X "}) == "X"
    assert report_mod._title({"title": "  "}) is None
    assert report_mod._title({"title": 3}) is None
    assert report_mod._title(None) is None


async def test_forced_events_filter_by_reason_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row("other", "a", "b"), _row("none", None, "b"), _row("other", "a", "c")]

    async def _rows(*_a: Any) -> list[_Row]:
        return rows

    monkeypatch.setattr(report_mod, "_rows", _rows)
    session: Any = object()
    everything = await report_mod.forced_events(session, TODAY, TODAY)
    assert len(everything) == 3
    assert len(await report_mod.forced_events(session, TODAY, TODAY, reason="other")) == 2
    path = await report_mod.forced_events(session, TODAY, TODAY, from_key="a", to_key="b")
    assert [e.reason for e in path] == ["other"]
    empty_from = await report_mod.forced_events(session, TODAY, TODAY, to_key="b")
    assert [e.reason for e in empty_from] == ["none"]
    assert (await report_mod.forced_report(session, TODAY, TODAY)).total == 3


async def test_rows_maps_the_query() -> None:
    app_id = uuid4()
    at = datetime(2026, 11, 19, tzinfo=UTC)
    db = fake_session(
        result(
            (app_id, {"title": "T"}, at, None, ".", "a", {"de": "A"}, "b", {"de": "B"}),
            (app_id, {}, at, "other", None, None, None, "b", None),
        )
    )
    rows = await report_mod._rows(db, TODAY, TODAY)
    assert [(r.reason, r.title, r.from_key) for r in rows] == [
        ("none", "T", "a"),
        ("other", None, None),
    ]


def test_meeting_date_is_not_in_the_future() -> None:
    now = datetime(2026, 11, 19, 22, 30, tzinfo=UTC)
    check_meeting_date(date(2026, 11, 19), now)
    check_meeting_date(date(2026, 11, 20), now)
    with pytest.raises(ValidationProblem):
        check_meeting_date(date(2026, 11, 21), now)


def test_outside_payload_stores_its_shape() -> None:
    gid, mid = uuid4(), uuid4()
    payload = OutsideDecisionIn.model_validate(
        {
            "result": "failed",
            "meetingDate": "2026-11-18",
            "gremiumId": str(gid),
            "no": 3,
            "meetingId": str(mid),
        }
    )
    assert payload.stored() == {
        "result": "failed",
        "meetingDate": "2026-11-18",
        "gremiumId": str(gid),
        "yes": None,
        "no": 3,
        "abstain": None,
        "meetingId": str(mid),
    }
    with pytest.raises(ValueError):
        OutsideDecisionIn.model_validate(
            {"result": "passed", "meetingDate": "2026-11-18", "gremiumId": str(gid), "yes": -1}
        )


async def test_outside_without_a_current_state_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    app = SimpleNamespace(id=uuid4(), current_state_id=None, email_confirmed_at=datetime.now(UTC))
    db = fake_session(result(app))
    payload = OutsideDecisionIn.model_validate(
        {"result": "passed", "meetingDate": "2026-11-18", "gremiumId": str(uuid4())}
    )
    with pytest.raises(ConflictError) as err:
        await outside_mod.record_outside_decision(
            FlowService(db),
            app.id,
            payload,
            Principal(sub="x"),
            now=datetime(2026, 11, 19, tzinfo=UTC),
        )
    assert err.value.code == "not_in_vote_state"


async def test_outside_meeting_check_maps_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.meetings import rules

    class _Rules:
        def __init__(self, _s: object) -> None: ...

        async def assert_can_read(self, *_a: object) -> None:
            raise ForbiddenError("no")

    monkeypatch.setattr(rules, "MeetingRules", _Rules)
    with pytest.raises(ValidationProblem) as err:
        await outside_mod._check_meeting(FlowService(fake_session()), uuid4(), Principal(sub="x"))
    assert err.value.code == "meeting_unknown"


async def test_failed_outside_decision_drops_a_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `failed` result never carries a decision, whatever the body holds."""
    state = SimpleNamespace(id=uuid4(), kind="vote")
    target = SimpleNamespace(id=uuid4(), is_approved=False)
    transition = SimpleNamespace(id=uuid4(), from_state_id=state.id, to_state_id=target.id)
    app = SimpleNamespace(
        id=uuid4(), current_state_id=state.id, email_confirmed_at=datetime.now(UTC), amount=None
    )
    db = fake_session(result(app))
    db.get_results = [state, target]
    db.scalar_results = [uuid4()]
    flow = FlowService(db)
    seen: dict[str, Any] = {}

    async def _branch(_self: FlowService, *_a: object) -> Any:
        return transition

    async def _stage(_self: FlowService, *_a: object, **kw: Any) -> StagedFire:
        seen.update(kw)
        return StagedFire(
            application=app,  # type: ignore[arg-type]
            transition=transition,  # type: ignore[arg-type]
            to_state_id=target.id,
            status_event_id=uuid4(),
            agenda_added=False,
            cancelled_vote_ids=(),
        )

    async def _cancel(_self: FlowService, *_a: object, **_kw: object) -> tuple[Any, ...]:
        return ("v1",)

    monkeypatch.setattr(FlowService, "branch_transition", _branch)
    monkeypatch.setattr(FlowService, "stage_fire", _stage)
    monkeypatch.setattr(FlowService, "_cancel_votes", _cancel)
    payload = OutsideDecisionIn.model_validate(
        {
            "result": "failed",
            "meetingDate": "2026-11-18",
            "gremiumId": str(uuid4()),
            "decision": {"approvedAmount": "1.00"},
        }
    )
    staged = await outside_mod.record_outside_decision(
        flow, app.id, payload, Principal(sub="x"), now=datetime(2026, 11, 19, tzinfo=UTC)
    )
    assert seen["decision"] is None
    assert seen["note"] == "outside:failed"
    assert staged.cancelled_vote_ids == ("v1",)


# --- routes ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def _read(*_a: object) -> None:
        return None

    monkeypatch.setattr(flow_router, "resolve_app_read", _read)
    application = create_app()
    application.dependency_overrides[get_current_applicant] = lambda: None
    return application


def _as(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="mgr", permissions=set(perms)
    )


def test_outside_route_needs_its_permission_and_commits(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 001603: 403 without `application.record_decision`."""
    calls: list[str] = []

    class _Session:
        async def commit(self) -> None:
            calls.append("commit")

    class _Flow:
        session = _Session()

        async def after_commit(self, staged: object) -> TransitionResult:
            calls.append("after")
            return TransitionResult(newStateId=uuid4(), statusEventId=uuid4())

    async def _record(*_a: object) -> object:
        calls.append("record")
        return object()

    monkeypatch.setattr(flow_router, "record_outside_decision", _record)
    app.dependency_overrides[get_flow_service] = lambda: _Flow()
    client = TestClient(app)
    body = {"result": "passed", "meetingDate": "2026-11-18", "gremiumId": str(uuid4())}
    url = f"/api/applications/{uuid4()}/outside-decision"
    _as(app, "application.force_status")
    assert client.post(url, json=body).status_code == 403
    _as(app, "application.record_decision")
    assert client.post(url, json=body).status_code == 200
    assert calls == ["record", "commit", "after"]


def test_forced_report_routes_need_audit_read(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 001651: the report needs `audit.read`; a reversed period gives 422."""

    async def _report(_db: object, start: date, end: date) -> Any:
        return summarize([], start, end)

    async def _events(_db: object, *_a: object, **kw: object) -> list[Any]:
        return []

    monkeypatch.setattr(forced_router, "forced_report", _report)
    monkeypatch.setattr(forced_router, "forced_events", _events)
    client = TestClient(app)
    _as(app, "application.force_status")
    assert client.get("/api/admin/forced-status").status_code == 403
    _as(app, "audit.read")
    ok = client.get("/api/admin/forced-status", params={"from": "2026-01-01", "to": "2026-02-01"})
    assert ok.status_code == 200
    assert ok.json()["from"] == "2026-01-01"
    assert client.get("/api/admin/forced-status").status_code == 200
    bad = client.get("/api/admin/forced-status", params={"from": "2026-03-01", "to": "2026-02-01"})
    assert bad.status_code == 422
    events = client.get("/api/admin/forced-status/events", params={"reason": "none"})
    assert events.status_code == 200
    assert events.json() == []
