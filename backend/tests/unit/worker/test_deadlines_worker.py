"""Cron worker `process_deadlines` (T-44): orchestration without a DB or Redis.

The tests fake the domain services for flow, voting and notifications. They cover the
worker logic. The worker skips a deadline when the row lock misses, because a parallel
worker holds that row. It sets the marker for idempotency. It catches Conflict and
NotFound. The tests also cover the reminder path and the mail queue choice.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from freezegun import freeze_time

import worker.deadlines as wd
from app.settings import load_settings
from app.shared.errors import ConflictError, NotFoundError

SETTINGS = load_settings()
FROZEN = "2026-06-07 12:00:00"
NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items
        # `rowcount` feeds DELETE and UPDATE statements, such as the guest application
        # discard.
        self.rowcount = len(items)

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._items

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None


class FakeSession:
    """`execute` returns pre-queued results and `scalar` returns one fixed value."""

    def __init__(self, results: list[list[Any]], scalar: Any = None) -> None:
        self._results = list(results)
        self._scalar = scalar
        self.committed = 0

    async def execute(self, _stmt: Any) -> FakeResult:
        return FakeResult(self._results.pop(0) if self._results else [])

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalar

    async def commit(self) -> None:
        self.committed += 1

    def add(self, _obj: Any) -> None: ...
    async def flush(self) -> None: ...
    async def rollback(self) -> None: ...


def _maker(sessions: list[FakeSession]) -> Any:
    """Build a fake sessionmaker.

    The maker hands out the given sessions in call order as async context managers.
    """
    it: Iterator[FakeSession] = iter(sessions)

    class _CM:
        def __init__(self, s: FakeSession) -> None:
            self.s = s

        async def __aenter__(self) -> FakeSession:
            return self.s

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    def make() -> _CM:
        return _CM(next(it))

    return make


class _FlowFake:
    calls: list[tuple[Any, ...]] = []

    def __init__(self, *_a: Any, **_k: Any) -> None: ...

    async def fire(self, app_id: Any, transition_id: Any, principal: Any, **kw: Any) -> Any:
        _FlowFake.calls.append((app_id, transition_id, kw))
        return SimpleNamespace(new_state_id=uuid4())


class _VotingFake:
    calls: list[Any] = []

    def __init__(self, *_a: Any, **_k: Any) -> None: ...

    async def close(self, vote_id: Any, principal: Any, *, now: Any = None) -> Any:
        _VotingFake.calls.append(vote_id)
        return SimpleNamespace()


class _NotifyFake:
    events: list[str] = []

    def __init__(self, *_a: Any, **_k: Any) -> None: ...

    async def handle_notify_action(self, action: dict[str, Any], **_kw: Any) -> int:
        _NotifyFake.events.append(action.get("templateKey", ""))
        return 1


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    _FlowFake.calls = []
    _VotingFake.calls = []
    _NotifyFake.events = []
    yield


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wd, "FlowService", _FlowFake)
    monkeypatch.setattr(wd, "VotingService", _VotingFake)
    monkeypatch.setattr(wd, "NotificationService", _NotifyFake)
    monkeypatch.setattr(wd, "build_notify_dispatcher", lambda _pool: object())


def _ctx(sessions: list[FakeSession]) -> dict[str, Any]:
    return {"settings": SETTINGS, "deadlines_sessionmaker": _maker(sessions)}


@freeze_time(FROZEN)
async def test_fire_due_deadline_fires_and_consumes(patched: None) -> None:
    tid = uuid4()
    deadline = SimpleNamespace(
        id=uuid4(), kind="requeue", application_id=uuid4(),
        action_on_pass={"transitionId": str(tid)},
    )
    lock = FakeSession([[deadline]])
    fired = await wd._fire_one(_ctx([lock]), deadline.id, NOW)
    assert fired is True
    assert _FlowFake.calls[0][1] == tid
    assert _FlowFake.calls[0][2]["deadline_passed"] is True
    assert _FlowFake.calls[0][2]["manual"] is False
    assert deadline.action_on_pass is None  # consumed
    assert lock.committed == 1


@freeze_time(FROZEN)
async def test_fire_lock_miss_skips(patched: None) -> None:
    # The lock returns None because another worker holds the row. Nothing fires.
    lock = FakeSession([[]])
    assert await wd._fire_one(_ctx([lock]), uuid4(), NOW) is False
    assert _FlowFake.calls == []


@freeze_time(FROZEN)
async def test_fire_conflict_still_consumes(patched: None, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom(_FlowFake):
        async def fire(self, *_a: Any, **_k: Any) -> Any:
            raise ConflictError("guard", code="conflict")

    monkeypatch.setattr(wd, "FlowService", _Boom)
    deadline = SimpleNamespace(
        id=uuid4(), kind="flow", application_id=uuid4(),
        action_on_pass={"transitionId": str(uuid4())},
    )
    lock = FakeSession([[deadline]])
    assert await wd._fire_one(_ctx([lock]), deadline.id, NOW) is False
    assert deadline.action_on_pass is None  # consumed even so
    assert lock.committed == 1


@freeze_time(FROZEN)
async def test_fire_notfound_consumes(patched: None, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Gone(_FlowFake):
        async def fire(self, *_a: Any, **_k: Any) -> Any:
            raise NotFoundError("missing")

    monkeypatch.setattr(wd, "FlowService", _Gone)
    deadline = SimpleNamespace(
        id=uuid4(), kind="flow", application_id=uuid4(),
        action_on_pass={"transitionId": str(uuid4())},
    )
    lock = FakeSession([[deadline]])
    assert await wd._fire_one(_ctx([lock]), deadline.id, NOW) is False
    assert deadline.action_on_pass is None


@freeze_time(FROZEN)
async def test_fire_bad_action_ref_consumed_without_fire(patched: None) -> None:
    deadline = SimpleNamespace(
        id=uuid4(), kind="flow", application_id=None, action_on_pass={"foo": "bar"}
    )
    lock = FakeSession([[deadline]])
    assert await wd._fire_one(_ctx([lock]), deadline.id, NOW) is False
    assert _FlowFake.calls == []
    assert deadline.action_on_pass is None


@freeze_time(FROZEN)
async def test_close_due_vote(patched: None) -> None:
    vote = SimpleNamespace(id=uuid4())
    lock = FakeSession([[vote]])
    assert await wd._close_one(_ctx([lock]), vote.id, NOW) is True
    assert _VotingFake.calls == [vote.id]


@freeze_time(FROZEN)
async def test_close_meeting_vote_broadcasts_vote_closed(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Send the `vote_closed` broadcast on cron auto-close (AUD-045).

    Only the REST router fires this broadcast otherwise. Without it, the beamer view and
    the voters stay on "open".
    """
    meeting_id = uuid4()
    closed = SimpleNamespace(
        id=uuid4(),
        meeting_id=meeting_id,
        result="passed",
        tally=SimpleNamespace(counts={"yes": 1}, failed_reason=None),
    )

    class _Closing(_VotingFake):
        async def close(self, vote_id: Any, principal: Any, *, now: Any = None) -> Any:
            _VotingFake.calls.append(vote_id)
            return closed

    monkeypatch.setattr(wd, "VotingService", _Closing)

    published: list[tuple[str, Any]] = []

    class _FakeRedis:
        async def publish(self, channel: str, message: Any) -> None:
            published.append((channel, message))

    vote = SimpleNamespace(id=uuid4())
    ctx = _ctx([FakeSession([[vote]])])
    ctx["redis"] = _FakeRedis()
    assert await wd._close_one(ctx, vote.id, NOW) is True
    # One broadcast goes to the meeting channel of the vote.
    assert len(published) == 1
    assert str(meeting_id) in published[0][0]


@freeze_time(FROZEN)
async def test_close_standalone_vote_no_broadcast(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Send no live-vote broadcast for a standalone vote with `meeting_id` None."""
    closed = SimpleNamespace(
        id=uuid4(),
        meeting_id=None,
        result="passed",
        tally=SimpleNamespace(counts={"yes": 1}, failed_reason=None),
    )

    class _Closing(_VotingFake):
        async def close(self, vote_id: Any, principal: Any, *, now: Any = None) -> Any:
            _VotingFake.calls.append(vote_id)
            return closed

    monkeypatch.setattr(wd, "VotingService", _Closing)

    published: list[Any] = []

    class _FakeRedis:
        async def publish(self, channel: str, message: Any) -> None:
            published.append(channel)

    vote = SimpleNamespace(id=uuid4())
    ctx = _ctx([FakeSession([[vote]])])
    ctx["redis"] = _FakeRedis()
    assert await wd._close_one(ctx, vote.id, NOW) is True
    assert published == []


@freeze_time(FROZEN)
async def test_close_broadcast_failure_does_not_fail_close(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the committed close intact when the message broker fails."""
    closed = SimpleNamespace(
        id=uuid4(),
        meeting_id=uuid4(),
        result="passed",
        tally=SimpleNamespace(counts={"yes": 1}, failed_reason=None),
    )

    class _Closing(_VotingFake):
        async def close(self, vote_id: Any, principal: Any, *, now: Any = None) -> Any:
            _VotingFake.calls.append(vote_id)
            return closed

    monkeypatch.setattr(wd, "VotingService", _Closing)

    class _BoomRedis:
        async def publish(self, channel: str, message: Any) -> None:
            raise RuntimeError("redis down")

    vote = SimpleNamespace(id=uuid4())
    ctx = _ctx([FakeSession([[vote]])])
    ctx["redis"] = _BoomRedis()
    assert await wd._close_one(ctx, vote.id, NOW) is True


@freeze_time(FROZEN)
async def test_close_lock_miss(patched: None) -> None:
    assert await wd._close_one(_ctx([FakeSession([[]])]), uuid4(), NOW) is False
    assert _VotingFake.calls == []


@freeze_time(FROZEN)
async def test_close_conflict_skips(patched: None, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom(_VotingFake):
        async def close(self, *_a: Any, **_k: Any) -> Any:
            raise ConflictError("already closed", code="conflict")

    monkeypatch.setattr(wd, "VotingService", _Boom)
    vote = SimpleNamespace(id=uuid4())
    assert await wd._close_one(_ctx([FakeSession([[vote]])]), vote.id, NOW) is False


@freeze_time(FROZEN)
async def test_close_notfound_skips(patched: None, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Gone(_VotingFake):
        async def close(self, *_a: Any, **_k: Any) -> Any:
            raise NotFoundError("app gone")

    monkeypatch.setattr(wd, "VotingService", _Gone)
    vote = SimpleNamespace(id=uuid4())
    assert await wd._close_one(_ctx([FakeSession([[vote]])]), vote.id, NOW) is False


@freeze_time(FROZEN)
async def test_remind_with_application_type_lookup(patched: None) -> None:
    deadline = SimpleNamespace(
        id=uuid4(), kind="vote", application_id=uuid4(), type_id=None,
        due_at=NOW + timedelta(hours=1), reminded_at=None,
    )
    lock = FakeSession([[deadline]], scalar=uuid4())  # the type_id lookup
    sent = await wd._remind_one(_ctx([lock]), SETTINGS, deadline.id, NOW, timedelta(hours=24))
    assert sent is True
    assert _NotifyFake.events == ["deadline_approaching"]
    assert deadline.reminded_at == NOW
    assert lock.committed == 1


@freeze_time(FROZEN)
async def test_remind_type_only_deadline_no_lookup(patched: None) -> None:
    deadline = SimpleNamespace(
        id=uuid4(), kind="phase", application_id=None, type_id=uuid4(),
        due_at=NOW + timedelta(hours=1), reminded_at=None,
    )
    lock = FakeSession([[deadline]])  # no scalar needed
    sent = await wd._remind_one(_ctx([lock]), SETTINGS, deadline.id, NOW, timedelta(hours=24))
    assert sent is True


@freeze_time(FROZEN)
async def test_remind_lock_miss(patched: None) -> None:
    lock = FakeSession([[]])
    assert await wd._remind_one(_ctx([lock]), SETTINGS, uuid4(), NOW, timedelta(hours=24)) is False
    assert _NotifyFake.events == []


def _deadline(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(), "kind": "flow", "application_id": uuid4(), "type_id": uuid4(),
        "action_on_pass": {"transitionId": str(uuid4())},
        "due_at": NOW + timedelta(hours=1), "reminded_at": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


@freeze_time(FROZEN)
async def test_reminder_failure_does_not_abort_cycle(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    class _RaiseOnce(_NotifyFake):
        async def handle_notify_action(self, action: dict[str, Any], **kw: Any) -> int:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("broken template")
            return await super().handle_notify_action(action, **kw)

    monkeypatch.setattr(wd, "NotificationService", _RaiseOnce)
    bad, good = _deadline(), _deadline()
    sessions = [
        FakeSession([[bad.id, good.id]]),  # scan
        FakeSession([[bad]]),              # lock bad → dispatch raises
        FakeSession([[good]]),             # lock good → ok
    ]
    # The worker logs and skips the broken deadline. It still processes the good one.
    assert await wd._process_reminders(_ctx(sessions), SETTINGS, NOW) == 1
    assert _NotifyFake.events == ["deadline_approaching"]


@freeze_time(FROZEN)
async def test_action_failure_does_not_abort_cycle(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    class _RaiseOnce(_FlowFake):
        async def fire(self, *a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return await super().fire(*a, **k)

    monkeypatch.setattr(wd, "FlowService", _RaiseOnce)
    bad, good = _deadline(), _deadline()
    sessions = [
        FakeSession([[bad.id, good.id]]),
        FakeSession([[bad]]),
        FakeSession([[good]]),
    ]
    assert await wd._process_actions(_ctx(sessions), SETTINGS, NOW) == 1
    assert len(_FlowFake.calls) == 1  # only the good deadline fires


@freeze_time(FROZEN)
async def test_vote_failure_does_not_abort_cycle(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    class _RaiseOnce(_VotingFake):
        async def close(self, *a: Any, **k: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return await super().close(*a, **k)

    monkeypatch.setattr(wd, "VotingService", _RaiseOnce)
    bad, good = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    sessions = [
        FakeSession([[bad.id, good.id]]),
        FakeSession([[bad]]),
        FakeSession([[good]]),
    ]
    assert await wd._process_votes(_ctx(sessions), NOW) == 1
    assert _VotingFake.calls == [good.id]


@freeze_time(FROZEN)
async def test_process_deadlines_orchestrates_all(patched: None) -> None:
    tid = uuid4()
    deadline = SimpleNamespace(
        id=uuid4(), kind="flow", application_id=uuid4(), type_id=uuid4(),
        action_on_pass={"transitionId": str(tid)},
    )
    rem = SimpleNamespace(
        id=uuid4(), kind="vote", application_id=None, type_id=uuid4(),
        due_at=NOW + timedelta(hours=1), reminded_at=None,
    )
    vote = SimpleNamespace(id=uuid4())
    # Call order of the maker: rem-scan, rem-lock, act-scan, act-lock, vote-scan,
    # vote-lock.
    sessions = [
        FakeSession([[rem.id]]),       # reminder scan
        FakeSession([[rem]]),          # reminder lock
        FakeSession([[deadline.id]]),  # action scan
        FakeSession([[deadline]]),     # action lock
        FakeSession([[vote.id]]),      # vote scan
        FakeSession([[vote]]),         # vote lock
        FakeSession([[]]),             # auto-transition scan (#8/#28) → no applications
        FakeSession([[]]),             # discard of unconfirmed guest applications → none
    ]
    out = await wd.process_deadlines(_ctx(sessions))
    assert out == "reminders=1 actions=1 votes=1 auto=0 discarded=0"


@freeze_time(FROZEN)
async def test_process_actions_counts_zero_on_lock_miss(patched: None) -> None:
    # The scan finds an id, but the lock misses because another worker holds the row.
    sessions = [FakeSession([[uuid4()]]), FakeSession([[]])]
    assert await wd._process_actions(_ctx(sessions), SETTINGS, NOW) == 0


@freeze_time(FROZEN)
async def test_process_reminders_counts_zero_on_lock_miss(patched: None) -> None:
    sessions = [FakeSession([[uuid4()]]), FakeSession([[]])]
    assert await wd._process_reminders(_ctx(sessions), SETTINGS, NOW) == 0


@freeze_time(FROZEN)
async def test_process_votes_counts_zero_on_lock_miss(patched: None) -> None:
    sessions = [FakeSession([[uuid4()]]), FakeSession([[]])]
    assert await wd._process_votes(_ctx(sessions), NOW) == 0


async def test_on_startup_sets_settings() -> None:
    ctx: dict[str, Any] = {}
    await wd.on_startup(ctx)
    assert "settings" in ctx


def test_mail_queue_from_pool_and_injection() -> None:
    assert wd._mail_queue({}) is None
    sentinel = object()
    assert wd._mail_queue({"mail_queue": sentinel}) is sentinel
    assert wd._mail_queue({"redis": object()}) is not None


def test_system_principal_has_manage() -> None:
    p = wd._system_principal()
    assert "application.manage" in p.permissions


def test_sessionmaker_default_falls_back() -> None:
    assert wd._sessionmaker({}) is not None


def test_now_is_tz_aware() -> None:
    assert wd._now().tzinfo is not None
