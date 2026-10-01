"""Unit tests: unconfirmed guest applications rest in the flow (F15, F18, O14).

The suite runs without a DB. `FlowService` reads through the result-queue fake. The
integration suite `test_unconfirmed_guest_rest` covers the same rules on Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.schemas import TransitionResult
from app.modules.flow.service import FlowService
from app.shared.errors import ConflictError, NotFoundError
from tests._support.flow_fakes import fake_session, result


class _Recorder:
    def __init__(self) -> None:
        self.batches: list[Sequence[DispatchedAction]] = []

    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        self.batches.append(list(actions))


def _app(*, confirmed: bool, state_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        current_state_id=state_id,
        flow_version_id=uuid4(),
        email_confirmed_at=datetime.now(UTC) if confirmed else None,
    )


# F15: `_load_app` hides an unconfirmed application from the routes.
async def test_load_app_hides_unconfirmed_from_routes() -> None:
    app = _app(confirmed=False)
    svc = FlowService(fake_session(result(app)))
    with pytest.raises(NotFoundError):
        await svc._load_app(app.id, allow_unconfirmed=False)  # noqa: SLF001


async def test_load_app_keeps_unconfirmed_for_internal_callers() -> None:
    app = _app(confirmed=False)
    svc = FlowService(fake_session(result(app)))
    assert await svc._load_app(app.id) is app  # noqa: SLF001


async def test_load_app_returns_confirmed_to_routes() -> None:
    app = _app(confirmed=True)
    svc = FlowService(fake_session(result(app)))
    assert await svc._load_app(app.id, allow_unconfirmed=False) is app  # noqa: SLF001


async def test_load_app_missing_404() -> None:
    svc = FlowService(fake_session(result()))
    with pytest.raises(NotFoundError):
        await svc._load_app(uuid4(), allow_unconfirmed=False)  # noqa: SLF001


@pytest.mark.parametrize(
    "call",
    [
        "available_transitions",
        "available_applicant_transitions",
        "fire",
        "fire_as_applicant",
        "list_states",
        "force_status",
    ],
)
async def test_route_methods_404_for_unconfirmed(call: str) -> None:
    """Every method that a flow route calls passes the flag on to `_load_app`."""
    app = _app(confirmed=False, state_id=uuid4())
    principal = Principal(sub="mgr", roles=["chair"], permissions=set())
    applicant_transition = SimpleNamespace(
        id=uuid4(), automatic=False, guard={"actorIsApplicant": True}
    )
    queue = [result(applicant_transition)] if call == "fire_as_applicant" else []
    svc = FlowService(fake_session(*queue, result(app)))
    calls: dict[str, Any] = {
        "available_transitions": lambda: svc.available_transitions(
            app.id, principal, allow_unconfirmed=False
        ),
        "available_applicant_transitions": lambda: svc.available_applicant_transitions(
            app.id, allow_unconfirmed=False
        ),
        "fire": lambda: svc.fire(app.id, uuid4(), principal, allow_unconfirmed=False),
        "fire_as_applicant": lambda: svc.fire_as_applicant(
            app.id, applicant_transition.id, allow_unconfirmed=False
        ),
        "list_states": lambda: svc.list_states(app.id, allow_unconfirmed=False),
        "force_status": lambda: svc.force_status(
            app.id, uuid4(), principal, note="x", allow_unconfirmed=False
        ),
    }
    with pytest.raises(NotFoundError):
        await calls[call]()


# F18/O14: `start_confirmed` starts the flow after the confirmation.
@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the deadline and auto-advance steps and record their calls."""
    record: dict[str, Any] = {"scheduled": [], "advanced": [], "outcome": None}

    async def _schedule(_self: FlowService, app: object, state: object) -> None:
        record["scheduled"].append((app, state))

    async def _advance(
        _self: FlowService, application_id: UUID, principal: Principal
    ) -> TransitionResult | None:
        record["advanced"].append((application_id, principal))
        outcome = record["outcome"]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(FlowService, "schedule_state_deadline", _schedule)
    monkeypatch.setattr(FlowService, "auto_advance", _advance)
    return record


async def test_start_confirmed_without_state_does_nothing(steps: dict[str, Any]) -> None:
    app = _app(confirmed=True)
    recorder = _Recorder()
    out = await FlowService(fake_session(result(app)), recorder).start_confirmed(app.id)
    assert out is None
    assert steps["scheduled"] == [] and steps["advanced"] == []
    assert recorder.batches == []


async def test_start_confirmed_schedules_advances_and_announces(
    steps: dict[str, Any],
) -> None:
    state = SimpleNamespace(id=uuid4())
    app = _app(confirmed=True, state_id=state.id)
    db = fake_session(result(app), result(state))
    event_id = uuid4()
    db.scalar_results.append(event_id)
    recorder = _Recorder()

    out = await FlowService(db, recorder).start_confirmed(app.id)

    assert out is None
    assert steps["scheduled"] == [(app, state)]
    (advanced_id, actor), = steps["advanced"]
    assert advanced_id == app.id
    assert actor.sub == "system:confirmation"
    # No transition fired, so the task mail of the initial state goes out, keyed on the
    # status event. A second start with the same event gives the same key.
    (batch,) = recorder.batches
    (action,) = batch
    assert action.type == "taskNotify"
    assert action.transition_id is None
    assert action.status_event_id == event_id
    assert action.idempotency_key == f"{app.id}:{event_id}:auto:task"


async def test_start_confirmed_missing_state_row_skips_the_deadline(
    steps: dict[str, Any],
) -> None:
    app = _app(confirmed=True, state_id=uuid4())
    db = fake_session(result(app), result())  # the state row is gone
    recorder = _Recorder()
    await FlowService(db, recorder).start_confirmed(app.id)
    assert steps["scheduled"] == []
    # Without the deadline step the start still commits the confirmation, so the
    # dispatchers see it in their own sessions.
    assert db.committed == 1
    assert len(steps["advanced"]) == 1
    # No status event: the announcement has no key and sends nothing.
    assert recorder.batches == []


async def test_start_confirmed_fired_transition_sends_no_extra_mail(
    steps: dict[str, Any],
) -> None:
    state = SimpleNamespace(id=uuid4())
    app = _app(confirmed=True, state_id=state.id)
    fired = TransitionResult(
        newStateId=uuid4(), statusEventId=uuid4(), dispatchedActions=["notify"]
    )
    steps["outcome"] = fired
    recorder = _Recorder()
    out = await FlowService(
        fake_session(result(app), result(state)), recorder
    ).start_confirmed(app.id)
    assert out is fired
    assert recorder.batches == []


@pytest.mark.parametrize("error", [ConflictError("race"), NotFoundError("gone")])
async def test_start_confirmed_swallows_a_failed_advance(
    steps: dict[str, Any], error: Exception
) -> None:
    state = SimpleNamespace(id=uuid4())
    app = _app(confirmed=True, state_id=state.id)
    steps["outcome"] = error
    recorder = _Recorder()
    out = await FlowService(
        fake_session(result(app), result(state)), recorder
    ).start_confirmed(app.id)
    assert out is None
    assert steps["scheduled"] == [(app, state)]
    assert recorder.batches == []


async def test_start_confirmed_logs_an_unexpected_advance_error(
    steps: dict[str, Any],
) -> None:
    """An unexpected error after the commit rolls back, logs and returns None."""
    state = SimpleNamespace(id=uuid4())
    app = _app(confirmed=True, state_id=state.id)
    steps["outcome"] = RuntimeError("budget action failed")
    db = fake_session(result(app), result(state))
    recorder = _Recorder()
    out = await FlowService(db, recorder).start_confirmed(app.id)
    assert out is None
    assert db.rolled_back == 1
    assert recorder.batches == []


class _FailingDispatcher:
    async def dispatch(self, actions: Sequence[DispatchedAction]) -> None:
        raise RuntimeError("mail queue down")


async def test_start_confirmed_logs_a_failed_announcement(
    steps: dict[str, Any],
) -> None:
    """A failed task mail enqueue does not fail the start."""
    state = SimpleNamespace(id=uuid4())
    app = _app(confirmed=True, state_id=state.id)
    db = fake_session(result(app), result(state))
    db.scalar_results.append(uuid4())
    out = await FlowService(db, _FailingDispatcher()).start_confirmed(app.id)
    assert out is None
    assert db.rolled_back == 1
