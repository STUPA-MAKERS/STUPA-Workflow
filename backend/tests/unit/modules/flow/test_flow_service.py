"""Unit tests for the flow and status engine (T-14, flows §3/§9).

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
        guard={"and": [{"roleIs": "chair"}, {"deadlinePassed": False}]},
        actions=[{"type": "notify", "recipients": [{"kind": "applicant"}]}],
    )
    rec = _Recorder()
    db = fake_session(result(app), result(transition), result(rowcount=1))
    svc = FlowService(db, rec)

    res = await svc.fire(app.id, transition.id, _principal(), note="los")

    assert res.new_state_id == review
    # The explicit notify action plus the implicit task mail (#4-3). The implicit
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
    # Without explicit actions the implicit auto mails stay (#4-3).
    assert res.dispatched_actions == ["notify", "taskNotify"]


# fire cancels the open votes on a non-branch exit (#abort-vote).
def _vote_cancel_updates(db) -> list:
    """Return the `UPDATE vote` statements of the session that cancel open votes."""
    return [
        s
        for s in db.statements
        if getattr(getattr(s, "table", None), "name", None) == "vote"
    ]


async def test_fire_manual_exit_cancels_open_votes() -> None:
    """A manual exit cancels the open votes of the application.

    A manual exit is for example "abort the vote" from a vote state. The service cancels
    the open votes in the same transaction.
    """
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


async def test_available_transitions_uses_explicit_deadline_passed() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    t = _transition(
        flow_id=flow_id, from_id=draft, to_id=uuid4(), guard={"deadlinePassed": True}
    )
    db = fake_session(result(app), result(t))  # no _deadline_passed query
    out = await FlowService(db).available_transitions(
        app.id, _principal(), deadline_passed=True
    )
    assert [x.id for x in out] == [t.id]


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


# branch_transition and fire_branch (#28).
async def test_auto_advance_with_explicit_deadline_skips_db_derive() -> None:
    # deadline_passed is set (not None), so the code derives nothing from the DB
    # (branch 308->310).
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    state = SimpleNamespace(id=draft, kind="normal", config={})
    manual = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4())  # automatic=False
    db = fake_session(result(app), result(state), result(manual))
    res = await FlowService(db).auto_advance(app.id, _principal(), deadline_passed=False)
    assert res is None


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


async def test_fire_materializes_deadline_of_entered_state() -> None:
    # to_state loads, so refresh(app) and schedule_state_deadline run (branch 481->482).
    flow_id, draft, review = uuid4(), uuid4(), uuid4()
    app = _app(draft, flow_id)
    t = _transition(flow_id=flow_id, from_id=draft, to_id=review)
    to_state = SimpleNamespace(id=review, config={})  # no policy key, so schedule only commits
    db = fake_session(
        result(app), result(t), result(rowcount=1),  # _load_app, _load_transition, UPDATE
        result(), result(), result(),  # _cancel_open_votes + audit (lock, prev-hash)
        result(to_state),  # _load_state(to_state)
        result(),  # schedule_state_deadline: DELETE of the old deadlines
    )
    res = await FlowService(db, _Recorder()).fire(app.id, t.id, _principal())
    assert res.new_state_id == review


async def test_fire_branch_404_when_no_matching_branch() -> None:
    flow_id, draft = uuid4(), uuid4()
    app = _app(draft, flow_id)
    fail = _transition(flow_id=flow_id, from_id=draft, to_id=uuid4(), branch="fail")
    db = fake_session(result(app), result(fail))
    with pytest.raises(NotFoundError, match="no 'pass' transition"):
        await FlowService(db).fire_branch(app.id, "pass", _principal())


async def test_schedule_deadline_unknown_policy_just_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PolSvc:
        def __init__(self, _session: object) -> None: ...

        async def get_by_key(self, _key: str) -> None:
            return None

    monkeypatch.setattr(flow_service, "DeadlinePolicyService", _PolSvc)
    app = SimpleNamespace(id=uuid4(), created_at=None, updated_at=None, flow_version_id=uuid4())
    state = SimpleNamespace(id=uuid4(), config={"deadlinePolicyKey": "missing"})
    db = fake_session(result())  # only the DELETE of the old deadlines
    await FlowService(db).schedule_state_deadline(app, state)  # pyright: ignore[reportArgumentType]
    assert db.committed == 1


async def test_schedule_deadline_unresolvable_due_just_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PolSvc:
        def __init__(self, _session: object) -> None: ...

        async def get_by_key(self, _key: str) -> SimpleNamespace:
            return SimpleNamespace(kind="absolute")

    monkeypatch.setattr(flow_service, "DeadlinePolicyService", _PolSvc)
    monkeypatch.setattr(flow_service, "resolve_due_at", lambda *_a, **_k: None)
    app = SimpleNamespace(id=uuid4(), created_at=None, updated_at=None, flow_version_id=uuid4())
    state = SimpleNamespace(id=uuid4(), config={"deadlinePolicyKey": "sem"})
    db = fake_session(result())
    await FlowService(db).schedule_state_deadline(app, state)  # pyright: ignore[reportArgumentType]
    assert db.committed == 1


# schedule_state_deadline picks the target transition by a satisfiable guard
# (#deadline-guard).
class _PolSvcOk:
    def __init__(self, _session: object) -> None: ...

    async def get_by_key(self, _key: str) -> SimpleNamespace:
        return SimpleNamespace(kind="absolute")


class _CaptureDeadlineService:
    """Intercept `DeadlineService.create` and keep the last `action_on_pass`."""

    last_action_on_pass: object = "<unset>"

    def __init__(self, _session: object) -> None: ...

    async def create(self, **kwargs: object) -> SimpleNamespace:
        _CaptureDeadlineService.last_action_on_pass = kwargs.get("action_on_pass")
        return SimpleNamespace(id=uuid4())


def _deadline_state_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(flow_service, "DeadlinePolicyService", _PolSvcOk)
    monkeypatch.setattr(
        flow_service, "resolve_due_at", lambda *_a, **_k: datetime_now()
    )
    monkeypatch.setattr(flow_service, "DeadlineService", _CaptureDeadlineService)
    _CaptureDeadlineService.last_action_on_pass = "<unset>"


def datetime_now() -> object:
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def test_schedule_deadline_picks_first_satisfiable_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two deadlinePassed candidates. Only the second one holds in the cron context.
    # action_on_pass must point to the second one, not always to the first one.
    _deadline_state_setup(monkeypatch)
    flow_id, src = uuid4(), uuid4()
    t1 = _transition(
        flow_id=flow_id, from_id=src, to_id=uuid4(),
        guard={"and": [{"deadlinePassed": True}, {"roleIs": "chair"}]},
    )
    t2 = _transition(
        flow_id=flow_id, from_id=src, to_id=uuid4(), guard={"deadlinePassed": True}
    )
    # eval_guard: t1 with roleIs fails in the role-free cron context. t2 holds.
    monkeypatch.setattr(
        flow_service, "eval_guard", lambda guard, _ctx: guard == t2.guard
    )
    app = SimpleNamespace(
        id=uuid4(), created_at=None, updated_at=None, flow_version_id=flow_id, data={}
    )
    state = SimpleNamespace(id=src, config={"deadlinePolicyKey": "sem"})
    db = fake_session(result(), result(t1, t2))  # DELETE old deadlines, then SELECT transitions
    await FlowService(db).schedule_state_deadline(app, state)  # pyright: ignore[reportArgumentType]
    assert _CaptureDeadlineService.last_action_on_pass == {"transitionId": str(t2.id)}


async def test_schedule_deadline_falls_back_to_first_when_none_satisfiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No candidate holds, so the code pins the first candidate as a pure marker.
    _deadline_state_setup(monkeypatch)
    flow_id, src = uuid4(), uuid4()
    t1 = _transition(
        flow_id=flow_id, from_id=src, to_id=uuid4(),
        guard={"and": [{"deadlinePassed": True}, {"roleIs": "chair"}]},
    )
    t2 = _transition(
        flow_id=flow_id, from_id=src, to_id=uuid4(),
        guard={"and": [{"deadlinePassed": True}, {"roleIs": "treasurer"}]},
    )
    monkeypatch.setattr(flow_service, "eval_guard", lambda *_a, **_k: False)
    app = SimpleNamespace(
        id=uuid4(), created_at=None, updated_at=None, flow_version_id=flow_id, data={}
    )
    state = SimpleNamespace(id=src, config={"deadlinePolicyKey": "sem"})
    db = fake_session(result(), result(t1, t2))
    await FlowService(db).schedule_state_deadline(app, state)  # pyright: ignore[reportArgumentType]
    assert _CaptureDeadlineService.last_action_on_pass == {"transitionId": str(t1.id)}


async def test_schedule_deadline_no_candidate_pins_null_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No deadlinePassed transition, so action_on_pass stays None (pure marker, _pick None).
    _deadline_state_setup(monkeypatch)
    flow_id, src = uuid4(), uuid4()
    t = _transition(
        flow_id=flow_id, from_id=src, to_id=uuid4(), guard={"roleIs": "chair"}
    )
    app = SimpleNamespace(
        id=uuid4(), created_at=None, updated_at=None, flow_version_id=flow_id, data={}
    )
    state = SimpleNamespace(id=src, config={"deadlinePolicyKey": "sem"})
    db = fake_session(result(), result(t))
    await FlowService(db).schedule_state_deadline(app, state)  # pyright: ignore[reportArgumentType]
    assert _CaptureDeadlineService.last_action_on_pass is None


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

    The revert writes the event and the audit entry. It skips the deadline reschedule.
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


async def test_revert_status_reschedules_restored_state_deadline() -> None:
    """Happy path with a loadable target state: the deadline reschedule branch runs."""
    to_id, from_id = uuid4(), uuid4()
    app = _app(to_id, uuid4())
    restored = SimpleNamespace(id=from_id, config={})
    # _load_app, UPDATE, record(lock, prev), _load_state→restored.
    db = fake_session(
        result(app), result(rowcount=1), result(), result(), result(restored)
    )
    await FlowService(db).revert_status(
        app.id, from_state_id=from_id, to_state_id=to_id, actor="admin",
        reverted_audit_id=7,
    )
    # schedule_state_deadline commits (delete plus an early return without a policy key).
    assert db.committed >= 1


# Tests for force_status (#force-status): a privileged direct override.
def _target_state(state_id: object, flow_id: object) -> SimpleNamespace:
    return SimpleNamespace(id=state_id, flow_version_id=flow_id, config={})


def _vote_cancel_stmts(db) -> list:
    return [
        s
        for s in db.statements
        if getattr(getattr(s, "table", None), "name", None) == "vote"
    ]


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
    cancels the open votes and materializes the deadline again.
    """
    flow_id, cur, target_id = uuid4(), uuid4(), uuid4()
    app = _app(cur, flow_id)
    target = _target_state(target_id, flow_id)
    to_state = SimpleNamespace(id=target_id, config={})  # no policy key, schedule only commits
    db = fake_session(
        result(app), result(target), result(rowcount=1),  # _load_app, _load_state, UPDATE
        result(), result(), result(),  # _cancel_open_votes + audit (lock, prev-hash)
        result(to_state),  # _load_state(to_state)
        result(),  # schedule_state_deadline: DELETE of the old deadlines
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
    # One UPDATE vote cancels the open votes.
    assert len(_vote_cancel_stmts(db)) == 1


async def test_force_status_happy_without_loadable_target_state() -> None:
    """A target state that does not load after the commit skips the deadline reschedule."""
    flow_id, cur, target_id = uuid4(), uuid4(), uuid4()
    app = _app(cur, flow_id)
    target = _target_state(target_id, flow_id)
    db = fake_session(
        result(app), result(target), result(rowcount=1),
        result(), result(), result(),  # cancel votes + audit
        result(),  # _load_state(to_state) → None
    )
    res = await FlowService(db).force_status(app.id, target_id, _principal(), note="x")
    assert res.new_state_id == target_id
    assert db.committed == 1  # only the force commit, no schedule commit


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
