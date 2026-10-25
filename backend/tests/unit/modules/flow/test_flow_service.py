"""Unit tests for the flow and status engine.

The suite runs without a DB. `FlowService` reads through a result-queue fake. The tests
patch the `fields_complete` signal, which keeps its own branch coverage in
`test_flow_context`. Every engine branch then takes a deterministic path.
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
from tests._support.flow_fakes import fake_session, result


class _Recorder:
    def __init__(self) -> None:
        self.batches: list[Sequence[DispatchedAction]] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.batches.append(list(actions))


@pytest.fixture(autouse=True)
def _ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace `build_context` with a DB-free stub.

    The stub takes the actor roles from the principal. Each test sets the other guard
    signals through the guards themselves.
    """

    async def _bc(
        _session: object,
        _app: object,
        principal: Principal,
        *,
        manual: bool,
        as_applicant: bool = False,
    ) -> GuardContext:
        return GuardContext(
            manual=manual,
            roles=frozenset(principal.roles) if manual else frozenset(),
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
        data={},
        budget_id=None,
        vote_gremium_id=None,
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
    # A result branch of a vote or an approval never fires by hand.
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    passed = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="pass")
    failed = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="fail")
    db = fake_session(result(app), result(passed, failed))
    out = await FlowService(db).available_transitions(app.id, _principal())
    assert out == []


async def test_fire_branch_transition_manually_409() -> None:
    # A direct POST with the id of a branch transition must not set the vote outcome
    # behind the back of the vote.
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


async def test_fire_automatic_transition_manually_409() -> None:
    """The list hides an automatic transition, so the manual fire refuses it too."""
    app = _app(uuid4(), uuid4())
    transition = _transition(
        flow_id=app.flow_version_id, from_id=app.current_state_id, to_id=uuid4()
    )
    transition.automatic = True
    db = fake_session(result(app), result(transition))
    with pytest.raises(ConflictError, match="Automatic"):
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
    # Only the transition that actorIsApplicant opens. roleIs fails without a role.
    assert [t.id for t in out] == [t_open.id]


async def test_fire_as_applicant_rejects_unopened_transition() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    closed = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"roleIs": "chair"}
    )
    db = fake_session(result(closed))  # only _load_transition runs
    with pytest.raises(ForbiddenError):
        await FlowService(db).fire_as_applicant(app.id, closed.id)


async def test_fire_as_applicant_fires_opened_transition() -> None:
    flow_id, draft, accepted = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    opened = _transition(
        flow_id=flow_id, from_id=draft, to_id=accepted, guard={"actorIsApplicant": True}
    )
    # fire_as_applicant: _load_transition (gate check) → fire: _load_app, _load_transition, update.
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
    db = fake_session(result())  # no application
    with pytest.raises(NotFoundError):
        await FlowService(db).available_transitions(uuid4(), _principal())


async def test_fire_commits_status_event_and_dispatches() -> None:
    flow_id, draft, review = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    transition = _transition(
        flow_id=flow_id,
        from_id=draft,
        to_id=review,
        guard={"and": [{"roleIs": "chair"}, {"budgetFitsApplication": False}]},
        actions=[{"type": "notify", "recipients": [{"kind": "applicant"}]}],
    )
    rec = _Recorder()
    db = fake_session(result(app), result(transition), result(rowcount=1))
    svc = FlowService(db, rec)

    res = await svc.fire(app.id, transition.id, _principal(), note="los")

    assert res.new_state_id == review
    # The explicit notify action plus the implicit task mail. The implicit
    # applicant mail drops out, because the explicit action already reaches the applicant.
    assert res.dispatched_actions == ["notify", "taskNotify"]
    assert db.committed == 1
    event = db.added[0]
    assert event.from_state_id == draft
    assert event.to_state_id == review
    assert event.transition_id == transition.id
    assert event.actor == "mgr-1"
    assert event.note == "los"
    # status_event_id comes from the flushed event.
    assert res.status_event_id == event.id
    assert rec.batches and rec.batches[0][0].type == "notify"


async def test_fire_unknown_application_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await FlowService(db).fire(uuid4(), uuid4(), _principal())


async def test_fire_unknown_transition_404() -> None:
    app = _app(uuid4(), uuid4())
    db = fake_session(result(app), result())  # the transition is missing
    with pytest.raises(NotFoundError):
        await FlowService(db).fire(app.id, uuid4(), _principal())


async def test_fire_transition_other_flow_404() -> None:
    app = _app(uuid4(), uuid4())
    transition = _transition(
        flow_id=uuid4(), from_id=app.current_state_id, to_id=uuid4()
    )  # a different flow_version
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
    """Without a dispatcher the service uses the NullActionDispatcher, with no effect."""
    flow_id, draft, to = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    transition = _transition(flow_id=flow_id, from_id=draft, to_id=to)
    db = fake_session(result(app), result(transition), result(rowcount=1))
    res = await flow_service.FlowService(db).fire(app.id, transition.id, _principal())
    assert res.new_state_id == to
    # Without explicit actions the implicit auto mails stay.
    assert res.dispatched_actions == ["notify", "taskNotify"]


# fire cancels the open votes on a non-branch exit.
def _vote_cancel_updates(db) -> list:
    """Return the locking `SELECT ... FROM vote` statements that load the votes to cancel."""
    return [
        s
        for s in db.statements
        if "FROM vote" in str(s) and "FOR UPDATE" in str(s)
    ]


def _open_vote(application_id: object, *, status: str = "open", opens_state_id: object = None):
    return SimpleNamespace(
        id=uuid4(),
        application_id=application_id,
        meeting_id=None,
        eligible_group="g",
        status=status,
        opens_state_id=opens_state_id,
        closed_at=None,
    )


async def test_fire_manual_exit_cancels_open_votes() -> None:
    """A manual exit cancels the open votes of the application.

    A manual exit is for example "abort the vote" from a vote state. The service cancels
    the open votes in the same transaction.
    """
    flow_id, voting, aborted = uuid4(), uuid4(), uuid4()
    app = _app(voting, flow_id)
    abort = _transition(flow_id=flow_id, from_id=voting, to_id=aborted)
    vote = _open_vote(app.id)
    # A draft of the state the application leaves goes.
    draft = _open_vote(app.id, status="draft", opens_state_id=voting)
    # A draft of the state the application enters stays (it belongs to that state).
    kept = _open_vote(app.id, status="draft", opens_state_id=aborted)
    db = fake_session(
        result(app), result(abort), result(rowcount=1), result(vote, draft, kept)
    )
    res = await FlowService(db, _Recorder()).fire(app.id, abort.id, _principal())
    assert res.new_state_id == aborted
    updates = _vote_cancel_updates(db)
    assert len(updates) == 1
    compiled = str(updates[0])
    assert "status" in compiled and "application_id" in compiled
    assert vote.status == "cancelled" and vote.closed_at is not None
    assert draft.status == "cancelled" and draft.closed_at is not None
    assert kept.status == "draft" and kept.closed_at is None


async def test_fire_publishes_vote_cancelled_after_commit() -> None:
    """Each cancelled vote goes out as `vote_cancelled`. A broker fault is logged."""
    flow_id, voting, aborted = uuid4(), uuid4(), uuid4()
    app = _app(voting, flow_id)
    abort = _transition(flow_id=flow_id, from_id=voting, to_id=aborted)
    first, second = _open_vote(app.id), _open_vote(app.id)
    db = fake_session(
        result(app), result(abort), result(rowcount=1), result(first, second)
    )

    class _Pub:
        def __init__(self) -> None:
            self.sent: list[object] = []

        async def vote_cancelled(self, vote: object) -> None:
            if not self.sent:
                self.sent.append(vote)
                raise RuntimeError("broker down")
            self.sent.append(vote)

    loaded: list[object] = []

    async def _get(_self: object, vote_id: object) -> object:
        loaded.append(vote_id)
        return vote_id

    from app.modules.voting.service import VotingService

    pub = _Pub()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(VotingService, "get", _get)
        await FlowService(db, _Recorder(), pub).fire(  # type: ignore[arg-type]
            app.id, abort.id, _principal()
        )
    assert loaded == [first.id, second.id]
    assert pub.sent == [first.id, second.id]
    assert db.committed >= 1


async def test_fire_branch_exit_does_not_cancel_votes() -> None:
    """A vote result branch cancels nothing.

    `close()` already closed the vote. A cancel would overwrite the vote that just
    closed.
    """
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
    """#requires-action: the flag travels into `TransitionOut` for the tasks-tab filter."""
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
    """#vote-bypass: auto_advance never fires out of a vote state.

    An old flow can still hold an automatic transition out of a vote state. The vote
    decides the state. Otherwise an application could reach "accepted" without a vote.
    """
    flow_id, voting = uuid4(), uuid4()
    app = _app(voting, flow_id)
    auto_exit = _transition(flow_id=flow_id, from_id=voting, to_id=uuid4())
    auto_exit.automatic = True
    vote_state = SimpleNamespace(id=voting, kind="vote", config={"gremiumId": "g"})
    # _load_app → _load_state (vote!) → stop before _outgoing.
    db = fake_session(result(app), result(vote_state))
    res = await FlowService(db).auto_advance(app.id, _principal())
    assert res is None
    assert db.committed == 0


async def test_applicant_transitions_empty_when_no_current_state() -> None:
    app = _app(None, uuid4())
    db = fake_session(result(app))
    assert await FlowService(db).available_applicant_transitions(app.id) == []


async def test_auto_advance_none_when_no_current_state() -> None:
    app = _app(None, uuid4())
    db = fake_session(result(app))
    assert await FlowService(db).auto_advance(app.id, _principal()) is None


async def test_auto_advance_no_matching_automatic_returns_none() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    state = SimpleNamespace(id=draft, kind="normal", config={})
    manual = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())  # automatic=False
    db = fake_session(result(app), result(state), result(manual))
    assert await FlowService(db).auto_advance(app.id, _principal()) is None


async def test_auto_advance_fires_matching_automatic_transition() -> None:
    flow_id, draft, done = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    state = SimpleNamespace(id=draft, kind="normal", config={})
    auto_t = _transition(flow_id=flow_id, from_id=draft, to_id=done)
    auto_t.automatic = True  # guard None, so it fires
    db = fake_session(
        result(app), result(state), result(auto_t),  # _load_app, _load_state, _outgoing
        result(app), result(auto_t), result(rowcount=1),  # fire(): load + update
    )
    res = await FlowService(db).auto_advance(app.id, _principal())
    assert res is not None
    assert res.new_state_id == done


# branch_transition and fire_branch.
async def test_branch_transition_returns_none_when_absent() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    fail = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="fail")
    db = fake_session(result(app), result(fail))
    assert await FlowService(db).branch_transition(app.id, "pass") is None


async def test_branch_transition_finds_matching_branch() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    passed = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="pass")
    db = fake_session(result(app), result(passed))
    assert await FlowService(db).branch_transition(app.id, "pass") is passed


async def test_fire_branch_fires_matching_branch() -> None:
    flow_id, draft, done = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    passed = _transition(flow_id=flow_id, from_id=draft, to_id=done, branch="pass")
    db = fake_session(
        result(app), result(passed),  # branch_transition: _load_app, _outgoing
        result(app), result(passed), result(rowcount=1),  # fire(): load + update
    )
    res = await FlowService(db).fire_branch(app.id, "pass", _principal())
    assert res.new_state_id == done


async def test_fire_branch_404_when_no_matching_branch() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    fail = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="fail")
    db = fake_session(result(app), result(fail))
    with pytest.raises(NotFoundError, match="no 'pass' transition"):
        await FlowService(db).fire_branch(app.id, "pass", _principal())


# Tests for revert_status (#config-versioning: audit-log revert).
async def test_revert_status_stale_when_not_in_target_state() -> None:
    """Revert gives 409 stale_revert when the application left the target state."""
    to_id, from_id = uuid4(), uuid4()
    app = _app(uuid4(), uuid4())  # current_state_id != to_id
    db = fake_session(result(app))
    with pytest.raises(ConflictError) as ei:
        await FlowService(db).revert_status(
            app.id, from_state_id=from_id, to_state_id=to_id, actor="admin",
            reverted_audit_id=7,
        )
    assert ei.value.code == "stale_revert"


async def test_revert_status_conflict_when_update_rowcount_zero() -> None:
    """A concurrent transition between read and UPDATE gives rowcount 0: 409 and rollback."""
    to_id, from_id = uuid4(), uuid4()
    app = _app(to_id, uuid4())  # current == to_id
    db = fake_session(result(app), result(rowcount=0))
    with pytest.raises(ConflictError) as ei:
        await FlowService(db).revert_status(
            app.id, from_state_id=from_id, to_state_id=to_id, actor="admin",
            reverted_audit_id=7,
        )
    assert ei.value.code == "stale_revert"
    assert db.rolled_back == 1


async def test_revert_status_moves_back_without_restored_state() -> None:
    """Happy path with a target state that does not load.

    The revert writes the event and the audit entry.
    """
    to_id, from_id = uuid4(), uuid4()
    app = _app(to_id, uuid4())
    db = fake_session(result(app), result(rowcount=1))
    sid = await FlowService(db).revert_status(
        app.id, from_state_id=from_id, to_state_id=to_id, actor="admin",
        reverted_audit_id=7,
    )
    assert db.committed == 1
    event = db.added[0]
    assert event.from_state_id == to_id and event.to_state_id == from_id
    assert event.transition_id is None and event.note == "revert"
    assert sid == event.id


# Tests for force_status: a privileged direct override.
def _target_state(state_id: object, flow_id: object) -> SimpleNamespace:
    return SimpleNamespace(id=state_id, flow_version_id=flow_id, kind="normal", config={})


def _vote_cancel_stmts(db) -> list:
    return _vote_cancel_updates(db)


async def test_force_status_no_current_state_conflicts() -> None:
    """An application without a current state cannot be forced: 409."""
    app = _app(None, uuid4())
    db = fake_session(result(app))
    with pytest.raises(ConflictError) as ei:
        await FlowService(db).force_status(app.id, uuid4(), _principal(), note="x")
    assert ei.value.code == "conflict"
    assert db.committed == 0


async def test_force_status_unknown_target_state_404() -> None:
    """An unknown target state gives 404 and no state change."""
    flow_id = uuid4()
    app = _app(uuid4(), flow_id)
    db = fake_session(result(app), result())  # _load_state(target) → None
    with pytest.raises(NotFoundError):
        await FlowService(db).force_status(app.id, uuid4(), _principal(), note="x")
    assert db.committed == 0


async def test_force_status_foreign_flow_state_404() -> None:
    """A target state from another flow gives 404.

    The 404 prevents a cross-graph inconsistency.
    """
    flow_id, target_id = uuid4(), uuid4()
    app = _app(uuid4(), flow_id)
    foreign = _target_state(target_id, uuid4())  # a different flow_version
    db = fake_session(result(app), result(foreign))
    with pytest.raises(NotFoundError, match="does not belong"):
        await FlowService(db).force_status(app.id, target_id, _principal(), note="x")


async def test_force_status_same_state_conflicts() -> None:
    """A target state equal to the current state gives 409, because it is a no-op."""
    flow_id, cur = uuid4(), uuid4()
    app = _app(cur, flow_id)
    target = _target_state(cur, flow_id)
    db = fake_session(result(app), result(target))
    with pytest.raises(ConflictError) as ei:
        await FlowService(db).force_status(app.id, cur, _principal(), note="x")
    assert ei.value.code == "conflict"
    assert db.committed == 0


async def test_force_status_concurrent_change_409_rolls_back() -> None:
    """A concurrent change between read and UPDATE gives rowcount 0: 409 and rollback."""
    flow_id, cur, target_id = uuid4(), uuid4(), uuid4()
    app = _app(cur, flow_id)
    target = _target_state(target_id, flow_id)
    db = fake_session(result(app), result(target), result(rowcount=0))
    with pytest.raises(ConflictError) as ei:
        await FlowService(db).force_status(app.id, target_id, _principal(), note="x")
    assert ei.value.code == "conflict"
    assert db.rolled_back == 1
    assert db.committed == 0


async def test_force_status_happy_writes_event_audit_and_cancels_votes() -> None:
    """Happy path with a loadable target state.

    The service writes a StatusEvent without a transition and a forced audit entry. It
    cancels the open votes.
    """
    flow_id, cur, target_id = uuid4(), uuid4(), uuid4()
    app = _app(cur, flow_id)
    target = _target_state(target_id, flow_id)
    db = fake_session(
        result(app), result(target), result(rowcount=1),  # _load_app, _load_state, UPDATE
        result(), result(), result(),  # vote cancel SELECT + audit (lock, prev-hash)
    )
    res = await FlowService(db).force_status(
        app.id, target_id, _principal(), note="admin override"
    )
    assert res.new_state_id == target_id
    assert res.dispatched_actions == []  # silent: no notifications
    assert db.committed >= 1
    # An event without a transition, with a reason and an actor.
    event = db.added[0]
    assert event.from_state_id == cur
    assert event.to_state_id == target_id
    assert event.transition_id is None
    assert event.actor == "mgr-1"
    assert event.note == "admin override"
    # One locking SELECT loads the votes to cancel.
    assert len(_vote_cancel_stmts(db)) == 1


async def test_list_states_returns_flow_states() -> None:
    flow_id = uuid4()
    app = _app(uuid4(), flow_id)
    s1 = SimpleNamespace(
        id=uuid4(), key="draft", label_i18n={"de": "Entwurf"}, color=None,
        edit_allowed=True, kind="normal",
    )
    s2 = SimpleNamespace(
        id=uuid4(), key="done", label_i18n={}, color="#111",
        edit_allowed=False, kind="normal",
    )
    db = fake_session(result(app), result(s1, s2))
    out = await FlowService(db).list_states(app.id)
    assert [o.key for o in out] == ["draft", "done"]
    assert out[1].color == "#111"
    assert out[0].edit_allowed is True


async def test_list_states_unknown_application_404() -> None:
    db = fake_session(result())  # no application
    with pytest.raises(NotFoundError):
        await FlowService(db).list_states(uuid4())


# The agenda pick on a manual transition.
def test_agenda_gremium_id_reads_the_first_agenda_action() -> None:
    gid = uuid4()
    assert flow_service.agenda_gremium_id(None) is None
    assert flow_service.agenda_gremium_id([{"type": "notify"}]) is None
    assert flow_service.agenda_gremium_id(
        ["junk", {"type": "addToNextSession", "gremiumId": str(gid)}]
    ) == gid
    assert flow_service.agenda_gremium_id(
        [{"type": "addToNextSession", "gremiumId": "not-a-uuid"}]
    ) is None


async def test_available_flags_the_agenda_only_into_a_vote_state() -> None:
    # Only a fire into a vote state takes a meeting (`_check_agenda_meeting`). The UI
    # asks for one only where `addsToAgenda` is set.
    flow_id, draft, voting, done, gid = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    action = [{"type": "addToNextSession", "gremiumId": str(gid)}]
    to_vote = _transition(flow_id=flow_id, from_id=draft, to_id=voting, actions=action)
    to_done = _transition(flow_id=flow_id, from_id=draft, to_id=done, actions=action)
    plain = _transition(flow_id=flow_id, from_id=draft, to_id=voting)
    # _load_app, _outgoing; the target states come through `get`.
    db = fake_session(result(app), result(to_vote, to_done, plain))
    vote_state = SimpleNamespace(id=voting, kind="vote", config={"gremiumId": str(gid)})
    done_state = SimpleNamespace(id=done, kind="normal", config={})
    db.get_results = [vote_state, done_state, vote_state]

    out = {t.id: t for t in await FlowService(db).available_transitions(app.id, _principal())}
    assert (out[to_vote.id].adds_to_agenda, out[to_vote.id].agenda_gremium_id) == (True, gid)
    assert (out[to_done.id].adds_to_agenda, out[to_done.id].agenda_gremium_id) == (False, None)
    assert (out[plain.id].adds_to_agenda, out[plain.id].agenda_gremium_id) == (False, None)


async def test_fire_with_meeting_adds_in_tx_and_skips_the_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_id, draft, voting, gid, meeting_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    t = _transition(
        flow_id=flow_id, from_id=draft, to_id=voting,
        actions=[{"type": "addToNextSession", "gremiumId": str(gid)}],
    )
    calls: list[tuple[str, object]] = []

    async def _check(
        _self: object, transition: object, mid: object, _p: object, **_kw: object
    ) -> None:
        calls.append(("check", mid))

    async def _add(
        _self: object, app_id: object, mid: object, *, non_public: bool, actor: str
    ) -> None:
        calls.append(("add", (app_id, mid, non_public, actor)))

    monkeypatch.setattr(FlowService, "_check_agenda_meeting", _check)
    monkeypatch.setattr(FlowService, "_add_to_agenda_in_tx", _add)
    db = fake_session(
        result(app), result(t), result(rowcount=1),  # _load_app, _load_transition, UPDATE
        result(), result(), result(),  # vote cancel SELECT + audit (lock, prev-hash)
    )
    rec = _Recorder()
    res = await FlowService(db, rec).fire(
        app.id, t.id, _principal(), meeting_id=meeting_id, non_public=True
    )
    assert calls == [
        ("check", meeting_id),
        ("add", (app.id, meeting_id, True, _principal().sub)),
    ]
    assert "addToNextSession" not in res.dispatched_actions
    assert all(a.type != "addToNextSession" for a in rec.batches[0])


def _agenda_transition(gid: object | None = None) -> SimpleNamespace:
    actions = (
        [{"type": "addToNextSession", "gremiumId": str(gid)}] if gid is not None else []
    )
    return _transition(flow_id=uuid4(), from_id=uuid4(), to_id=uuid4(), actions=actions)


class _MeetingSvc:
    """Stand-in for `MeetingService` with a fixed read decision."""

    error: Exception | None = None

    def __init__(self, _session: object) -> None: ...

    async def assert_can_read(self, _meeting_id: object, _principal: object) -> None:
        if _MeetingSvc.error is not None:
            raise _MeetingSvc.error


@pytest.fixture
def meeting_svc(monkeypatch: pytest.MonkeyPatch) -> type[_MeetingSvc]:
    import app.modules.livevote.service as livevote_service

    _MeetingSvc.error = None
    monkeypatch.setattr(livevote_service, "MeetingService", _MeetingSvc)
    return _MeetingSvc


async def _check(
    transition: SimpleNamespace, *, to_state: object, meeting: object = None
) -> None:
    db = fake_session(result(to_state) if to_state is not None else result())
    db.get_results = [meeting]
    await FlowService(db)._check_agenda_meeting(
        transition, uuid4(), _principal()  # pyright: ignore[reportArgumentType]
    )


@pytest.mark.parametrize("case", ["no_action", "no_state", "normal_state"])
async def test_check_agenda_meeting_refuses_the_transition(
    meeting_svc: type[_MeetingSvc], case: str
) -> None:
    from app.shared.errors import ValidationProblem

    gid = uuid4()
    transition = _agenda_transition(None if case == "no_action" else gid)
    to_state = None if case == "no_state" else SimpleNamespace(kind="normal")
    if case == "no_action":
        to_state = SimpleNamespace(kind="vote")
    with pytest.raises(ValidationProblem):
        await _check(transition, to_state=to_state)


@pytest.mark.parametrize("case", ["hidden", "missing", "live", "other_gremium"])
async def test_check_agenda_meeting_refuses_the_meeting(
    meeting_svc: type[_MeetingSvc], case: str
) -> None:
    from app.shared.errors import ValidationProblem

    gid = uuid4()
    meeting: object = SimpleNamespace(status="planned", gremium_id=gid)
    if case == "hidden":
        meeting_svc.error = ForbiddenError("no")
    elif case == "missing":
        meeting = None
    elif case == "live":
        meeting = SimpleNamespace(status="live", gremium_id=gid)
    else:
        meeting = SimpleNamespace(status="planned", gremium_id=uuid4())
    with pytest.raises(ValidationProblem) as exc:
        await _check(
            _agenda_transition(gid), to_state=SimpleNamespace(kind="vote"), meeting=meeting
        )
    assert exc.value.code == "agenda_meeting_invalid"


async def test_check_agenda_meeting_accepts_a_fitting_meeting(
    meeting_svc: type[_MeetingSvc],
) -> None:
    gid = uuid4()
    await _check(
        _agenda_transition(gid),
        to_state=SimpleNamespace(kind="vote"),
        meeting=SimpleNamespace(status="planned", gremium_id=gid),
    )


@pytest.mark.parametrize("error", [None, ConflictError("no"), NotFoundError("gone")])
async def test_add_to_agenda_in_tx(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None
) -> None:
    import app.modules.livevote.agenda_service as agenda_mod
    from app.shared.errors import ValidationProblem

    added: list[tuple[object, object, bool, str]] = []

    class _Agenda:
        def __init__(self, _session: object) -> None: ...

        async def add_in_tx(
            self, meeting_id: object, *, application_id: object, non_public: bool, actor: str
        ) -> bool:
            if error is not None:
                raise error
            added.append((meeting_id, application_id, non_public, actor))
            return True

    monkeypatch.setattr(agenda_mod, "AgendaService", _Agenda)
    db = fake_session()
    app_id, meeting_id = uuid4(), uuid4()
    svc = FlowService(db)
    if error is None:
        await svc._add_to_agenda_in_tx(
            app_id, meeting_id, non_public=False, actor="mgr"
        )
        assert added == [(meeting_id, app_id, False, "mgr")]
        assert db.rolled_back == 0
    else:
        with pytest.raises(ValidationProblem):
            await svc._add_to_agenda_in_tx(
                app_id, meeting_id, non_public=False, actor="mgr"
            )
        assert db.rolled_back == 1


async def test_stage_branch_race_leaves_the_rollback_to_the_savepoint() -> None:
    """A lost race in the vote close does not roll back the whole transaction.

    The vote close stages its branch in a SAVEPOINT. A full rollback here would also
    drop the staged vote close, so `stage_branch` raises without a rollback.
    """
    flow_id, voting = uuid4(), uuid4()
    app = _app(voting, flow_id)
    passed = _transition(flow_id=flow_id, from_id=voting, to_id=uuid4(), branch="pass")
    db = fake_session(
        result(app),  # branch_transition: _load_app
        result(passed),  # branch_transition: the pass exit
        result(app),  # stage_fire: _load_app
        result(passed),  # stage_fire: _load_transition
        result(rowcount=0),  # the optimistic UPDATE lost the race
    )
    with pytest.raises(ConflictError):
        await FlowService(db, _Recorder()).stage_branch(app.id, "pass", _principal())
    assert db.rolled_back == 0
    assert db.committed == 0


