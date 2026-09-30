"""F6 without a DB: `FlowOps._move_state_deadlines` and its marker rules.

The integration test `test_flow_activate_deadlines` runs the same path on Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.modules.flow.service as flow_service
from app.modules.admin.service import ConfigService

NOW = datetime.now(UTC)


class _Scalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _Session:
    def __init__(self, *batches: list[Any]) -> None:
        self._batches = list(batches)

    async def scalars(self, _stmt: Any) -> _Scalars:
        return _Scalars(self._batches.pop(0))


class _Flow:
    """Record the scheduled states and hand out the prepared deadlines."""

    made: dict[UUID, Any] = {}
    calls: list[tuple[UUID, Any, bool]] = []
    kept: dict[UUID, Any] = {}

    def __init__(self, _session: object) -> None: ...

    async def schedule_state_deadline(
        self, app: Any, state: Any, *, commit: bool, due_at: Any = None
    ) -> Any:
        _Flow.calls.append((app.id, state, commit))
        _Flow.kept[app.id] = due_at
        made = _Flow.made.get(app.id)
        if made is not None and due_at is not None:
            made.due_at = due_at
        return made


@pytest.fixture(autouse=True)
def _patch_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    _Flow.made = {}
    _Flow.calls = []
    _Flow.kept = {}
    monkeypatch.setattr(flow_service, "FlowService", _Flow)


async def test_no_moved_applications_is_a_no_op() -> None:
    svc = ConfigService(_Session())  # type: ignore[arg-type]
    await svc._move_state_deadlines({}, {}, None, {})  # noqa: SLF001
    assert _Flow.calls == []


async def test_markers_carry_over_only_for_an_unchanged_due_time() -> None:
    review = SimpleNamespace(key="review", config={})
    initial = SimpleNamespace(key="start", config={})
    same, moved, dropped, fresh, gone = (SimpleNamespace(id=uuid4()) for _ in range(5))
    past = NOW - timedelta(days=1)
    later = NOW + timedelta(days=3)
    reminded = NOW - timedelta(hours=1)
    old = [
        # Same due time, consumed and expired: both markers stay.
        SimpleNamespace(application_id=same.id, due_at=past, reminded_at=reminded,
                        action_on_pass=None),
        # A new due time: the markers do not carry over.
        SimpleNamespace(application_id=moved.id, due_at=later, reminded_at=reminded,
                        action_on_pass={"transitionId": "x"}),
        SimpleNamespace(application_id=dropped.id, due_at=later, reminded_at=None,
                        action_on_pass=None),
    ]
    _Flow.made = {
        same.id: SimpleNamespace(due_at=past, reminded_at=None,
                                 action_on_pass={"transitionId": "new"}),
        moved.id: SimpleNamespace(due_at=later + timedelta(days=1), reminded_at=None,
                                  action_on_pass={"transitionId": "new"}),
        fresh.id: SimpleNamespace(due_at=later, reminded_at=None,
                                  action_on_pass={"transitionId": "new"}),
    }
    keys = {same.id: "review", moved.id: "review", dropped.id: "review",
            fresh.id: "gone-key", gone.id: "gone-key"}
    session = _Session(old, [same, moved, dropped, fresh, gone])
    svc = ConfigService(session)  # type: ignore[arg-type]

    await svc._move_state_deadlines(keys, {"review": review}, initial, {})  # type: ignore[arg-type]  # noqa: SLF001

    assert _Flow.made[same.id].reminded_at == reminded
    assert _Flow.made[same.id].action_on_pass is None
    assert _Flow.made[moved.id].reminded_at is None
    assert _Flow.made[moved.id].action_on_pass == {"transitionId": "new"}
    assert _Flow.made[fresh.id].action_on_pass == {"transitionId": "new"}
    # A removed key falls back to the initial state; every call leaves the commit open.
    by_app = {app_id: (state, commit) for app_id, state, commit in _Flow.calls}
    assert by_app[fresh.id] == (initial, False)
    assert by_app[same.id] == (review, False)


async def test_same_due_time_keeps_an_open_action() -> None:
    app = SimpleNamespace(id=uuid4())
    due = NOW + timedelta(days=2)
    old = [SimpleNamespace(application_id=app.id, due_at=due, reminded_at=None,
                           action_on_pass={"transitionId": "old"})]
    _Flow.made = {app.id: SimpleNamespace(due_at=due, reminded_at=None,
                                          action_on_pass={"transitionId": "new"})}
    svc = ConfigService(_Session(old, [app]))  # type: ignore[arg-type]
    await svc._move_state_deadlines(  # noqa: SLF001
        {app.id: "review"}, {"review": SimpleNamespace(config={})}, None, {}  # type: ignore[arg-type]
    )
    assert _Flow.made[app.id].action_on_pass == {"transitionId": "new"}


async def test_no_state_skips_the_application() -> None:
    app = SimpleNamespace(id=uuid4())
    svc = ConfigService(_Session([], [app]))  # type: ignore[arg-type]
    await svc._move_state_deadlines({app.id: "gone"}, {}, None, {})  # noqa: SLF001
    assert _Flow.calls == []


async def test_same_policy_key_keeps_the_old_due_time() -> None:
    """A kept `deadlinePolicyKey` passes the old due time on and keeps the markers.

    Without it a `recurring` policy resolves to its next date after now, and an
    expired, consumed deadline would move and fire again.
    """
    kept, changed, fresh = (SimpleNamespace(id=uuid4()) for _ in range(3))
    past = NOW - timedelta(days=1)
    reminded = NOW - timedelta(days=2)
    review = SimpleNamespace(key="review", config={"deadlinePolicyKey": "rec"})
    old = [
        SimpleNamespace(application_id=kept.id, due_at=past, reminded_at=reminded,
                        action_on_pass=None),
        SimpleNamespace(application_id=changed.id, due_at=past, reminded_at=reminded,
                        action_on_pass=None),
    ]
    later = NOW + timedelta(days=30)
    _Flow.made = {
        kept.id: SimpleNamespace(due_at=later, reminded_at=None,
                                 action_on_pass={"transitionId": "new"}),
        changed.id: SimpleNamespace(due_at=later, reminded_at=None,
                                    action_on_pass={"transitionId": "new"}),
        fresh.id: SimpleNamespace(due_at=later, reminded_at=None,
                                  action_on_pass={"transitionId": "new"}),
    }
    keys = {kept.id: "review", changed.id: "review", fresh.id: "review"}
    olds = {kept.id: "rec", changed.id: "other", fresh.id: "rec"}
    svc = ConfigService(_Session(old, [kept, changed, fresh]))  # type: ignore[arg-type]

    await svc._move_state_deadlines(keys, {"review": review}, None, olds)  # type: ignore[arg-type]  # noqa: SLF001

    assert _Flow.kept == {kept.id: past, changed.id: None, fresh.id: None}
    assert _Flow.made[kept.id].due_at == past
    assert _Flow.made[kept.id].reminded_at == reminded
    assert _Flow.made[kept.id].action_on_pass is None
    assert _Flow.made[changed.id].due_at == later
    assert _Flow.made[changed.id].reminded_at is None
    assert _Flow.made[changed.id].action_on_pass == {"transitionId": "new"}
