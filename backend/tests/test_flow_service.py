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
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError
from app.shared.guards import GuardContext
from tests.flow_fakes import fake_session, result


class _Recorder:
    def __init__(self) -> None:
        self.batches: list[Sequence[DispatchedAction]] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.batches.append(list(actions))


@pytest.fixture(autouse=True)
def _ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    """``build_context`` ohne DB: liefert die Akteur-Rollen aus dem Principal (Guard-
    Signale je Test über die Guards selbst gesetzt)."""

    async def _bc(
        _session: object,
        _app: object,
        principal: Principal,
        *,
        manual: bool,
        deadline_passed: bool = False,
        as_applicant: bool = False,
    ) -> GuardContext:
        return GuardContext(
            manual=manual,
            roles=frozenset(principal.roles) if manual else frozenset(),
            deadline_passed=deadline_passed,
            actor_is_applicant=as_applicant,
        )

    monkeypatch.setattr(flow_context, "build_context", _bc)


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
    branch: str | None = None,
    requires_action: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        flow_version_id=flow_id,
        from_state_id=from_id,
        to_state_id=to_id,
        label_i18n={"de": "Einreichen"},
        color=None,
        guard=guard,
        actions=actions if actions is not None else [],
        automatic=False,
        branch=branch,
        requires_action=requires_action,
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


async def test_available_excludes_result_branches() -> None:
    # Vote/Approval-Ergebnis-Branches (branch gesetzt) sind nie manuell feuerbar.
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    passed = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="pass")
    failed = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="fail")
    db = fake_session(result(app), result(passed, failed))
    out = await FlowService(db).available_transitions(app.id, _principal())
    assert out == []


async def test_fire_branch_transition_manually_409() -> None:
    # Direkter POST mit der id eines Branch-Übergangs darf den Vote-Ausgang nicht
    # an der Abstimmung vorbei setzen.
    app = _app(uuid4(), uuid4())
    transition = _transition(
        flow_id=app.flow_version_id,
        from_id=app.current_state_id,
        to_id=uuid4(),
        branch="pass",
    )
    db = fake_session(result(app), result(transition))
    with pytest.raises(ConflictError):
        await FlowService(db).fire(app.id, transition.id, _principal())
    assert db.committed == 0


async def test_applicant_transitions_only_actor_is_applicant_gated() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    t_open = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"actorIsApplicant": True}
    )
    t_closed = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"roleIs": "chair"}
    )
    db = fake_session(result(app), result(t_open, t_closed))
    out = await FlowService(db).available_applicant_transitions(app.id)
    # Nur der actorIsApplicant-freigegebene Übergang; roleIs greift mangels Rolle nicht.
    assert [t.id for t in out] == [t_open.id]


async def test_fire_as_applicant_rejects_unopened_transition() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    closed = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"roleIs": "chair"}
    )
    db = fake_session(result(closed))  # nur _load_transition wird erreicht
    with pytest.raises(ForbiddenError):
        await FlowService(db).fire_as_applicant(app.id, closed.id)


async def test_fire_as_applicant_fires_opened_transition() -> None:
    flow_id, draft, accepted = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    opened = _transition(
        flow_id=flow_id, from_id=draft, to_id=accepted, guard={"actorIsApplicant": True}
    )
    # fire_as_applicant: _load_transition (Gate-Check) → fire: _load_app, _load_transition, update.
    db = fake_session(result(opened), result(app), result(opened), result(rowcount=1))
    res = await FlowService(db).fire_as_applicant(app.id, opened.id, note="ok")
    assert res.new_state_id == accepted
    assert db.committed == 1


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
        guard={"and": [{"roleIs": "chair"}, {"deadlinePassed": False}]},
        actions=[{"type": "notify", "recipients": [{"kind": "applicant"}]}],
    )
    rec = _Recorder()
    db = fake_session(result(app), result(transition), result(rowcount=1))
    svc = FlowService(db, rec)

    res = await svc.fire(app.id, transition.id, _principal(), note="los")

    assert res.new_state_id == review
    assert res.dispatched_actions == ["notify"]
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


# --------------------------------------------------------------------------- #
# fire — Vote-Storno bei Nicht-Branch-Ausgang (#abort-vote)
# --------------------------------------------------------------------------- #
def _vote_cancel_updates(db) -> list:
    """Alle ``UPDATE vote``-Statements der Session (Storno offener Abstimmungen)."""
    return [
        s
        for s in db.statements
        if getattr(getattr(s, "table", None), "name", None) == "vote"
    ]


async def test_fire_manual_exit_cancels_open_votes() -> None:
    """Manueller Ausgang (z. B. »Wahl abbrechen« aus einem vote-State): offene
    Abstimmungen des Antrags werden in derselben Transaktion storniert."""
    flow_id, voting, aborted = uuid4(), uuid4(), uuid4()
    app = _app(voting, flow_id)
    abort = _transition(flow_id=flow_id, from_id=voting, to_id=aborted)
    db = fake_session(result(app), result(abort), result(rowcount=1))
    res = await FlowService(db, _Recorder()).fire(app.id, abort.id, _principal())
    assert res.new_state_id == aborted
    updates = _vote_cancel_updates(db)
    assert len(updates) == 1
    compiled = str(updates[0])
    assert "status" in compiled and "application_id" in compiled


async def test_fire_branch_exit_does_not_cancel_votes() -> None:
    """Der Vote-Ergebnis-Branch storniert nichts — close() hat den Vote bereits
    geschlossen (sonst würde der frisch geschlossene Vote überschrieben)."""
    flow_id, voting = uuid4(), uuid4()
    app = _app(voting, flow_id)
    passed = _transition(
        flow_id=flow_id, from_id=voting, to_id=uuid4(), branch="pass"
    )
    db = fake_session(result(app), result(passed), result(rowcount=1))
    await FlowService(db, _Recorder()).fire(
        app.id, passed.id, _principal(), manual=False
    )
    assert _vote_cancel_updates(db) == []


async def test_available_transitions_carry_requires_action_flag() -> None:
    """#requires-action: das Flag reist bis in ``TransitionOut`` (Tasks-Tab-Filter)."""
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    required = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())
    optional = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), requires_action=False
    )
    db = fake_session(result(app), result(required, optional))
    out = await FlowService(db).available_transitions(app.id, _principal())
    assert [(t.id, t.requires_action) for t in out] == [
        (required.id, True),
        (optional.id, False),
    ]


async def test_auto_advance_never_fires_out_of_vote_states() -> None:
    """#vote-bypass: auch wenn ein (Alt-)Flow eine automatische Transition aus dem
    vote-State enthält, feuert auto_advance sie NIE — den State entscheidet die
    Abstimmung, sonst wäre der Antrag »angenommen«, ohne dass je abgestimmt wurde."""
    flow_id, voting = uuid4(), uuid4()
    app = _app(voting, flow_id)
    auto_exit = _transition(flow_id=flow_id, from_id=voting, to_id=uuid4())
    auto_exit.automatic = True
    vote_state = SimpleNamespace(id=voting, kind="vote", config={"gremiumId": "g"})
    # _load_app → _load_state (vote!) → Abbruch VOR _outgoing.
    db = fake_session(result(app), result(vote_state))
    res = await FlowService(db).auto_advance(app.id, _principal())
    assert res is None
    assert db.committed == 0
