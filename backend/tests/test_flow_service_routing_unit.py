"""Unit (ohne DB): FlowService-Auswahl für decision/vote/approval (#28).

Stubbt ``FlowService.fire`` (dessen interne Transaktion ist anderswo getestet) und
prüft nur, dass route_decision/fire_branch den *richtigen* Übergang auswählen.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.admin.models import ApplicationType
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.flow.models import State, Transition
from app.modules.flow.schemas import TransitionResult
from app.modules.flow.service import FlowService
from app.shared.errors import ConflictError, NotFoundError
from tests.auth_fakes import fake_session, result


def _state(key: str, *, kind: str = "normal", config: dict | None = None) -> State:
    s = State(
        flow_version_id=uuid4(),
        key=key,
        label_i18n={},
        category="running",
        kind=kind,
        config=config or {},
    )
    s.id = uuid4()
    return s


def _transition(frm: State, to: State, *, branch: str | None = None) -> Transition:
    t = Transition(
        flow_version_id=frm.flow_version_id,
        from_state_id=frm.id,
        to_state_id=to.id,
        label_i18n={},
        branch=branch,
    )
    t.id = uuid4()
    return t


def _app(state: State, *, amount=None) -> Application:
    a = Application(
        type_id=uuid4(),
        form_version_id=uuid4(),
        flow_version_id=state.flow_version_id,
        current_state_id=state.id,
        amount=None if amount is None else Decimal(str(amount)),
        data={},
    )
    a.id = uuid4()
    return a


def _app_type() -> ApplicationType:
    t = ApplicationType(key="grossantrag", name_i18n={}, has_budget=True)
    t.id = uuid4()
    return t


def _principal() -> Principal:
    return Principal(sub="actor", roles=["admin"], permissions={"flow.fire"})


def _stub_fire(svc: FlowService, calls: list) -> None:
    async def fake_fire(application_id, transition_id, principal, **kw):  # noqa: ANN001
        calls.append(transition_id)
        return TransitionResult(
            newStateId=uuid4(), statusEventId=uuid4(), dispatchedActions=[]
        )

    svc.fire = fake_fire  # type: ignore[method-assign]


async def test_route_decision_fires_threshold_branch() -> None:
    dec = _state(
        "decide",
        kind="decision",
        config={
            "rules": [{"when": {"field": "amount", "op": ">=", "value": 500}, "to": "big"}],
            "else": "small",
        },
    )
    big, small = _state("big"), _state("small")
    t_big, t_small = _transition(dec, big), _transition(dec, small)
    app = _app(dec, amount=600)
    # execute order: _decision_facts→ApplicationType, _outgoing→transitions,
    # then _load_state for each candidate until match (t_big first → 1 lookup).
    db = fake_session(
        result(_app_type()),
        result(t_big, t_small),
        result(big),
    )
    svc = FlowService(db)
    calls: list = []
    _stub_fire(svc, calls)
    await svc.route_decision(app.id, _principal(), app=app, state=dec)
    assert calls == [t_big.id]


async def test_route_decision_falls_back_to_else() -> None:
    dec = _state(
        "decide",
        kind="decision",
        config={
            "rules": [{"when": {"field": "amount", "op": ">=", "value": 500}, "to": "big"}],
            "else": "small",
        },
    )
    big, small = _state("big"), _state("small")
    t_big, t_small = _transition(dec, big), _transition(dec, small)
    app = _app(dec, amount=100)  # below threshold → else "small"
    db = fake_session(
        result(_app_type()),
        result(t_big, t_small),
        result(big),  # t_big.to → "big" ≠ "small"
        result(small),  # t_small.to → "small" → match
    )
    svc = FlowService(db)
    calls: list = []
    _stub_fire(svc, calls)
    await svc.route_decision(app.id, _principal(), app=app, state=dec)
    assert calls == [t_small.id]


async def test_route_decision_noop_when_not_decision() -> None:
    normal = _state("open")
    app = _app(normal)
    svc = FlowService(fake_session())
    assert await svc.route_decision(app.id, _principal(), app=app, state=normal) is None


async def test_route_decision_raises_when_no_matching_transition() -> None:
    dec = _state(
        "decide",
        kind="decision",
        config={"rules": [], "else": "ghost"},
    )
    other = _state("other")
    t = _transition(dec, other)
    app = _app(dec)
    db = fake_session(result(_app_type()), result(t), result(other))
    svc = FlowService(db)
    _stub_fire(svc, [])
    with pytest.raises(ConflictError):
        await svc.route_decision(app.id, _principal(), app=app, state=dec)


async def test_fire_branch_picks_matching_branch() -> None:
    vote = _state("vote", kind="vote", config={"gremiumId": str(uuid4())})
    passed, failed = _state("passed"), _state("rejected")
    t_pass = _transition(vote, passed, branch="pass")
    t_fail = _transition(vote, failed, branch="fail")
    app = _app(vote)
    # _load_app → app; _outgoing → transitions
    db = fake_session(result(app), result(t_fail, t_pass))
    svc = FlowService(db)
    calls: list = []
    _stub_fire(svc, calls)
    await svc.fire_branch(app.id, "pass", _principal())
    assert calls == [t_pass.id]


async def test_fire_branch_unknown_branch_raises() -> None:
    vote = _state("vote", kind="vote", config={"gremiumId": str(uuid4())})
    passed = _state("passed")
    t_pass = _transition(vote, passed, branch="pass")
    app = _app(vote)
    db = fake_session(result(app), result(t_pass))
    svc = FlowService(db)
    _stub_fire(svc, [])
    with pytest.raises(NotFoundError):
        await svc.fire_branch(app.id, "fail", _principal())
