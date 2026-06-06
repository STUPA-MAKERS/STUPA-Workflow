"""TDD: Flow-/Status-Engine (T-14, flows §3/§9).

Unit-Suite ohne DB: ``FlowService`` liest über einen Ergebnis-Queue-Fake; das
``fields_complete``-Signal wird gepatcht (eigene Branch-Abdeckung in
``test_flow_context``), sodass jede Engine-Verzweigung deterministisch greift.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.flow import context as flow_context
from app.modules.flow import service as flow_service
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.service import FlowService
from app.shared.errors import ConflictError, NotFoundError
from tests.flow_fakes import fake_session, result


class _Recorder:
    def __init__(self) -> None:
        self.batches: list[Sequence[DispatchedAction]] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.batches.append(list(actions))


@pytest.fixture(autouse=True)
def _complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """``fields_complete`` per Default True (Guard-Signale gezielt je Test gesetzt)."""

    async def _fc(_session: object, _app: object) -> bool:
        return True

    monkeypatch.setattr(flow_context, "fields_complete", _fc)


def _principal(**over: object) -> Principal:
    base: dict[str, object] = {
        "sub": "mgr-1",
        "roles": ["chair"],
        "permissions": {"application.manage"},
    }
    base.update(over)
    return Principal(**base)  # type: ignore[arg-type]


def _app(state_id: object, flow_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        current_state_id=state_id,
        flow_version_id=flow_id,
        type_id=uuid4(),
        form_version_id=uuid4(),
        budget_pot_id=None,
        data={},
    )


def _transition(
    *,
    flow_id: object,
    from_id: object,
    to_id: object,
    guard: object = None,
    actions: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        flow_version_id=flow_id,
        from_state_id=from_id,
        to_state_id=to_id,
        label_i18n={"de": "Einreichen"},
        guard=guard,
        actions=actions if actions is not None else [],
    )


# --------------------------------------------------------------------------- #
# available_transitions
# --------------------------------------------------------------------------- #
async def test_available_filters_by_guard_and_order() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    t_ok = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"roleIs": "chair"}
    )
    t_blocked = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"roleIs": "treasurer"}
    )
    db = fake_session(result(app), result(t_ok, t_blocked))
    svc = FlowService(db)

    out = await svc.available_transitions(app.id, _principal())
    assert [t.id for t in out] == [t_ok.id]
    assert out[0].label == {"de": "Einreichen"}


async def test_available_empty_when_no_current_state() -> None:
    app = _app(None, uuid4())
    db = fake_session(result(app))
    out = await FlowService(db).available_transitions(app.id, _principal())
    assert out == []


async def test_available_unknown_application_404() -> None:
    db = fake_session(result())  # kein Antrag
    with pytest.raises(NotFoundError):
        await FlowService(db).available_transitions(uuid4(), _principal())


# --------------------------------------------------------------------------- #
# fire — happy path + dispatch
# --------------------------------------------------------------------------- #
async def test_fire_commits_status_event_and_dispatches() -> None:
    flow_id, draft, review = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    transition = _transition(
        flow_id=flow_id,
        from_id=draft,
        to_id=review,
        guard={"and": [{"roleIs": "chair"}, {"fieldsComplete": True}]},
        actions=[
            {"type": "notify", "group": "gremium"},
            {"type": "setEditLock", "locked": True},
        ],
    )
    rec = _Recorder()
    db = fake_session(result(app), result(transition), result(rowcount=1))
    svc = FlowService(db, rec)

    res = await svc.fire(app.id, transition.id, _principal(), note="los")

    assert res.new_state_id == review
    assert res.dispatched_actions == ["notify"]  # setEditLock inline
    assert db.committed == 1
    event = db.added[0]
    assert event.from_state_id == draft
    assert event.to_state_id == review
    assert event.transition_id == transition.id
    assert event.actor == "mgr-1"
    assert event.note == "los"
    # status_event_id stammt aus dem geflushten Event.
    assert res.status_event_id == event.id
    assert rec.batches and rec.batches[0][0].type == "notify"


# --------------------------------------------------------------------------- #
# fire — error branches
# --------------------------------------------------------------------------- #
async def test_fire_unknown_application_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await FlowService(db).fire(uuid4(), uuid4(), _principal())


async def test_fire_unknown_transition_404() -> None:
    app = _app(uuid4(), uuid4())
    db = fake_session(result(app), result())  # Transition fehlt
    with pytest.raises(NotFoundError):
        await FlowService(db).fire(app.id, uuid4(), _principal())


async def test_fire_transition_other_flow_404() -> None:
    app = _app(uuid4(), uuid4())
    transition = _transition(
        flow_id=uuid4(), from_id=app.current_state_id, to_id=uuid4()
    )  # anderer flow_version
    db = fake_session(result(app), result(transition))
    with pytest.raises(NotFoundError, match="does not belong"):
        await FlowService(db).fire(app.id, transition.id, _principal())


async def test_fire_wrong_from_state_409() -> None:
    flow_id = uuid4()
    app = _app(uuid4(), flow_id)
    transition = _transition(flow_id=flow_id, from_id=uuid4(), to_id=uuid4())
    db = fake_session(result(app), result(transition))
    with pytest.raises(ConflictError) as exc:
        await FlowService(db).fire(app.id, transition.id, _principal())
    assert exc.value.code == "conflict"


async def test_fire_guard_failed_409() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    transition = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"roleIs": "treasurer"}
    )
    db = fake_session(result(app), result(transition))
    with pytest.raises(ConflictError) as exc:
        await FlowService(db).fire(app.id, transition.id, _principal())
    assert exc.value.code == "guard_failed"


async def test_fire_concurrent_transition_409_rolls_back() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    transition = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())
    db = fake_session(result(app), result(transition), result(rowcount=0))
    svc = FlowService(db)
    with pytest.raises(ConflictError) as exc:
        await svc.fire(app.id, transition.id, _principal())
    assert exc.value.code == "conflict"
    assert db.rolled_back == 1
    assert db.committed == 0


async def test_fire_default_dispatcher_when_none() -> None:
    """Ohne Dispatcher greift der NullActionDispatcher (kein Fehler, kein Effekt)."""
    flow_id, draft, to = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    transition = _transition(flow_id=flow_id, from_id=draft, to_id=to)
    db = fake_session(result(app), result(transition), result(rowcount=1))
    res = await flow_service.FlowService(db).fire(app.id, transition.id, _principal())
    assert res.new_state_id == to
    assert res.dispatched_actions == []
