"""FlowService: the decision of a manual transition (F1)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.applications.decision import (
    CODE_AMOUNT_EXCEEDS,
    DecisionIn,
    not_allowed_problem,
)
from app.modules.flow import service as flow_service
from app.modules.flow.service import FlowService
from app.shared.errors import ValidationProblem
from tests._support.flow_fakes import fake_session, result
from tests.unit.modules.flow.test_flow_service import _app, _ctx, _principal, _transition

__all__ = ["_ctx"]  # the autouse fixture, imported for its side effect


class _Calls:
    def __init__(self) -> None:
        self.checks: list[str | None] = []
        self.records: list[dict[str, Any]] = []
        self.reverts: list[UUID | None] = []
        self.refuse = False


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    out = _Calls()

    async def _check(_session: Any, _app: Any, target_key: str | None) -> None:
        out.checks.append(target_key)
        if out.refuse:
            raise not_allowed_problem("no")

    async def _record(_session: Any, app: Any, decision: DecisionIn, **kw: Any) -> Any:
        out.records.append({"app": app, "decision": decision, **kw})
        return SimpleNamespace()

    async def _revert(_session: Any, _app: Any, event_id: UUID | None, **_kw: Any) -> None:
        out.reverts.append(event_id)

    monkeypatch.setattr(flow_service, "check_decision_target", _check)
    monkeypatch.setattr(flow_service, "record_decision", _record)
    monkeypatch.setattr(flow_service, "revert_decision_for_event", _revert)
    return out


def _decision_app(state: UUID, flow_id: UUID) -> SimpleNamespace:
    app = _app(state, flow_id)
    app.amount = Decimal("1000.00")
    app.approved_amount = Decimal("900.00")
    return app


async def test_fire_with_decision_sets_the_amount_and_records_it(calls: _Calls) -> None:
    flow_id, draft, approved = uuid4(), uuid4(), uuid4()
    app = _decision_app(draft, flow_id)
    transition = _transition(flow_id=flow_id, from_id=draft, to_id=approved)
    target = SimpleNamespace(id=approved, key="approved", kind="normal", config={})
    db = fake_session(result(app), result(transition), result(target), result(rowcount=1))
    decision = DecisionIn(approvedAmount=Decimal("800.00"), conditions=["A"])

    res = await FlowService(db).fire(app.id, transition.id, _principal(), decision=decision)

    assert calls.checks == ["approved"]
    assert app.approved_amount == Decimal("800.00")
    (rec,) = calls.records
    assert rec["decision"] is decision
    assert rec["old_approved"] == Decimal("900.00")
    assert rec["decided_by"] == "mgr-1"
    assert rec["actor"] == "mgr-1"
    assert rec["status_event_id"] == res.status_event_id


async def test_fire_with_decision_into_a_missing_state_is_refused(calls: _Calls) -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _decision_app(draft, flow_id)
    transition = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())
    calls.refuse = True
    db = fake_session(result(app), result(transition), result())
    with pytest.raises(ValidationProblem):
        await FlowService(db).fire(app.id, transition.id, _principal(), decision=DecisionIn())
    assert calls.checks == [None]
    assert calls.records == []
    assert app.approved_amount == Decimal("900.00")


async def test_fire_with_decision_above_the_request_is_refused(calls: _Calls) -> None:
    flow_id, draft, approved = uuid4(), uuid4(), uuid4()
    app = _decision_app(draft, flow_id)
    transition = _transition(flow_id=flow_id, from_id=draft, to_id=approved)
    target = SimpleNamespace(id=approved, key="approved")
    db = fake_session(result(app), result(transition), result(target))
    with pytest.raises(ValidationProblem) as exc:
        await FlowService(db).fire(
            app.id,
            transition.id,
            _principal(),
            decision=DecisionIn(approvedAmount=Decimal("1000.01")),
        )
    assert exc.value.code == CODE_AMOUNT_EXCEEDS
    assert calls.records == []
    assert app.approved_amount == Decimal("900.00")


async def test_fire_without_decision_records_nothing(calls: _Calls) -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    transition = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())
    db = fake_session(result(app), result(transition), result(rowcount=1))
    await FlowService(db).fire(app.id, transition.id, _principal())
    assert calls.checks == []
    assert calls.records == []


async def test_available_flags_transitions_into_accepted_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _accepted(_session: Any, _budget_id: Any) -> frozenset[str]:
        return frozenset({"approved"})

    monkeypatch.setattr(flow_service, "accepted_state_keys", _accepted)
    flow_id, draft, ok_id, no_id = uuid4(), uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    to_ok = _transition(flow_id=flow_id, from_id=draft, to_id=ok_id)
    to_no = _transition(flow_id=flow_id, from_id=draft, to_id=no_id)
    to_gone = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())
    db = fake_session(result(app), result(to_ok, to_no, to_gone))
    db.get_results = [
        SimpleNamespace(id=ok_id, key="approved", kind="normal", config={}),
        SimpleNamespace(id=no_id, key="review", kind="normal", config={}),
        None,
    ]
    out = {t.id: t for t in await FlowService(db).available_transitions(app.id, _principal())}
    assert out[to_ok.id].allows_decision is True
    assert out[to_no.id].allows_decision is False
    assert out[to_gone.id].allows_decision is False
    assert out[to_ok.id].model_dump(by_alias=True)["allowsDecision"] is True


async def test_available_without_accepted_states_flags_nothing() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    t = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())
    db = fake_session(result(app), result(t))
    out = await FlowService(db).available_transitions(app.id, _principal())
    assert out[0].allows_decision is False


async def test_revert_status_restores_the_decision_of_the_event(calls: _Calls) -> None:
    to_id, from_id, event_id = uuid4(), uuid4(), uuid4()
    app = _app(to_id, uuid4())
    db = fake_session(result(app), result(rowcount=1))
    await FlowService(db).revert_status(
        app.id,
        from_state_id=from_id,
        to_state_id=to_id,
        actor="admin",
        reverted_audit_id=7,
        reverted_status_event_id=event_id,
    )
    assert calls.reverts == [event_id]
