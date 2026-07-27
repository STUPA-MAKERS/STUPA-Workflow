"""Unit tests for `DeadlineService` (T-44): scans, locks, markers and helpers.

The real partial indexes and `FOR UPDATE SKIP LOCKED` live in the integration suite
(`tests/integration/test_deadlines_service.py`). Here a result-queue fake hits every
branch deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.deadlines.service import (
    DeadlineService,
    flow_deadline_passed,
    transition_ref,
)
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
LEAD = timedelta(hours=24)


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
    tid = uuid4()
    assert transition_ref({"transitionId": UUID(str(tid)).hex}) == tid


# flow_deadline_passed serves both FlowService and the task-mail recipients.
async def test_flow_deadline_passed_true_when_row_due() -> None:
    session = fake_session()
    session.scalar_results = [uuid4()]  # a due flow_deadline row exists
    assert await flow_deadline_passed(session, uuid4()) is True


async def test_flow_deadline_passed_false_without_due_row() -> None:
    # An empty scalar queue gives None, so no deadline is due.
    assert await flow_deadline_passed(fake_session(), uuid4()) is False
