"""TDD: DeadlineService (T-44) — Scans/Locks/Marker + Helfer ohne DB.

Die echten partiellen Indizes + ``FOR UPDATE SKIP LOCKED`` liegen in der Integration
(``tests/integration/test_deadlines_service.py``); hier wird jede Verzweigung über
einen Ergebnis-Queue-Fake deterministisch getroffen (Branch-Abdeckung)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.deadlines.service import DeadlineService, chunked, transition_ref
from tests.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
LEAD = timedelta(hours=24)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_transition_ref_camel_and_snake() -> None:
    tid = uuid4()
    assert transition_ref({"transitionId": str(tid)}) == tid
    assert transition_ref({"transition_id": str(tid)}) == tid


@pytest.mark.parametrize(
    "value",
    [None, {}, {"foo": "bar"}, {"transitionId": "not-a-uuid"}, {"transitionId": 123}],
)
def test_transition_ref_invalid_is_none(value: Any) -> None:
    assert transition_ref(value) is None


def test_chunked_splits_into_batches() -> None:
    ids = [uuid4() for _ in range(5)]
    assert chunked(ids, 2) == [ids[0:2], ids[2:4], ids[4:5]]
    assert chunked([], 3) == []


# --------------------------------------------------------------------------- #
# Scans
# --------------------------------------------------------------------------- #
async def test_due_action_deadline_ids() -> None:
    ids = [uuid4(), uuid4()]
    svc = DeadlineService(fake_session(result(*ids)))
    assert await svc.due_action_deadline_ids(NOW) == ids


async def test_due_reminder_ids() -> None:
    ids = [uuid4()]
    svc = DeadlineService(fake_session(result(*ids)))
    assert await svc.due_reminder_ids(NOW, LEAD) == ids


async def test_due_open_vote_ids() -> None:
    ids = [uuid4()]
    svc = DeadlineService(fake_session(result(*ids)))
    assert await svc.due_open_vote_ids(NOW) == ids


# --------------------------------------------------------------------------- #
# Locks (hit + miss)
# --------------------------------------------------------------------------- #
async def test_lock_action_deadline_hit_and_miss() -> None:
    deadline = SimpleNamespace(id=uuid4())
    svc = DeadlineService(fake_session(result(deadline)))
    assert await svc.lock_action_deadline(deadline.id, NOW) is deadline

    miss = DeadlineService(fake_session(result()))
    assert await miss.lock_action_deadline(uuid4(), NOW) is None


async def test_lock_reminder_hit() -> None:
    deadline = SimpleNamespace(id=uuid4())
    svc = DeadlineService(fake_session(result(deadline)))
    assert await svc.lock_reminder(deadline.id, NOW, LEAD) is deadline


async def test_lock_open_vote_hit() -> None:
    vote = SimpleNamespace(id=uuid4())
    svc = DeadlineService(fake_session(result(vote)))
    assert await svc.lock_open_vote(vote.id, NOW) is vote


# --------------------------------------------------------------------------- #
# Create + markers
# --------------------------------------------------------------------------- #
async def test_create_persists_and_commits() -> None:
    session = fake_session()
    svc = DeadlineService(session)
    tid = uuid4()
    deadline = await svc.create(
        kind="requeue",
        due_at=NOW,
        application_id=uuid4(),
        action_on_pass={"transitionId": str(tid)},
    )
    assert deadline.kind == "requeue"
    assert session.committed == 1
    assert deadline in session.added


async def test_consume_action_clears_and_commits() -> None:
    session = fake_session()
    deadline = SimpleNamespace(action_on_pass={"transitionId": str(uuid4())})
    await DeadlineService(session).consume_action(deadline)  # type: ignore[arg-type]
    assert deadline.action_on_pass is None
    assert session.committed == 1


async def test_mark_reminded_sets_timestamp_and_commits() -> None:
    session = fake_session()
    deadline = SimpleNamespace(reminded_at=None)
    await DeadlineService(session).mark_reminded(deadline, NOW)  # type: ignore[arg-type]
    assert deadline.reminded_at == NOW
    assert session.committed == 1


def test_uuid_roundtrip_in_ref() -> None:
    # Defensive: bereits-UUID-Objekt als String akzeptiert.
    tid = uuid4()
    assert transition_ref({"transitionId": UUID(str(tid)).hex}) == tid
