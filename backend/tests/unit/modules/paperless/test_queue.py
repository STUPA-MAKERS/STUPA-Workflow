"""The start of a filing run at an event (§F/integrations/paperless/002523).

The call puts one `process_paperless_filings` job into the queue. It does nothing without
a pool, and an error of the queue never reaches the action that asked.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.paperless_actions import PaperlessFilingDispatcher
from app.modules.paperless.queue import FILING_TASK_NAME, request_filing


class _Pool:
    """An arq pool that records the job names, or fails."""

    def __init__(self, *, broken: bool = False) -> None:
        self.jobs: list[str] = []
        self.broken = broken

    async def enqueue_job(self, name: str) -> None:
        if self.broken:
            raise ConnectionError("redis down")
        self.jobs.append(name)


def _action() -> DispatchedAction:
    return DispatchedAction(
        type="taskNotify",
        application_id=uuid4(),
        transition_id=uuid4(),
        status_event_id=uuid4(),
        idempotency_key="k",
    )


async def test_the_request_enqueues_one_filing_run() -> None:
    pool = _Pool()
    await request_filing(pool)
    assert pool.jobs == [FILING_TASK_NAME] == ["process_paperless_filings"]


async def test_the_request_does_nothing_without_a_pool() -> None:
    await request_filing(None)


async def test_a_broken_queue_does_not_fail_the_action(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _Pool(broken=True)
    await request_filing(pool)
    assert pool.jobs == []
    assert "paperless filing run was not enqueued" in caplog.text


async def test_a_committed_transition_asks_for_a_filing_run() -> None:
    pool = _Pool()
    dispatcher = PaperlessFilingDispatcher(pool)
    await dispatcher.dispatch([])
    assert pool.jobs == []
    await dispatcher.dispatch([_action(), _action()])
    assert pool.jobs == [FILING_TASK_NAME]


async def test_a_transition_does_not_fail_when_the_queue_is_broken() -> None:
    await PaperlessFilingDispatcher(_Pool(broken=True)).dispatch([_action()])
    await PaperlessFilingDispatcher(None).dispatch([_action()])
