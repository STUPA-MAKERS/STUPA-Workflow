"""Unit-Tests Render-Queue (T-20): Enqueue, Idempotenz-Dedupe, »kein Pool«."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.pdf.queue import (
    RENDER_TASK_NAME,
    ArqRenderQueue,
    render_queue_from_pool,
)


class _FakePool:
    def __init__(self, *, dedupe: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._dedupe = dedupe

    async def enqueue_job(self, name: str, arg: str, *, _job_id: str) -> Any:
        self.calls.append((name, arg, _job_id))
        return None if self._dedupe else object()


async def test_enqueue_uses_render_task_and_idempotent_job_id() -> None:
    pool = _FakePool()
    jid = uuid.uuid4()
    await ArqRenderQueue(pool).enqueue(jid)
    assert pool.calls == [(RENDER_TASK_NAME, str(jid), f"render:{jid}")]


async def test_enqueue_dedupe_is_silent() -> None:
    pool = _FakePool(dedupe=True)
    await ArqRenderQueue(pool).enqueue(uuid.uuid4())  # None-Rückgabe → kein Fehler
    assert len(pool.calls) == 1


def test_render_queue_from_pool_none() -> None:
    assert render_queue_from_pool(None) is None
    assert isinstance(render_queue_from_pool(_FakePool()), ArqRenderQueue)  # type: ignore[arg-type]
