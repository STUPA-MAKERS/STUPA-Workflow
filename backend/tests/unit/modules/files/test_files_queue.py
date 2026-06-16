"""Unit-Tests Scan-Queue (T-13): arq-Enqueue + idempotenter Job-Key."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.files.queue import ArqScanQueue, scan_queue_from_pool


class _FakePool:
    def __init__(self, job: object | None = object()) -> None:
        self.calls: list[tuple[str, str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self._job = job

    async def enqueue_job(self, task: str, arg: str, **kw: Any) -> object | None:
        self.calls.append((task, arg))
        self.kwargs.append(kw)
        return self._job


async def test_enqueue_uses_idempotent_job_id() -> None:
    pool = _FakePool()
    aid = uuid.uuid4()
    await ArqScanQueue(pool).enqueue(aid)
    assert pool.calls == [("scan_attachment", str(aid))]
    assert pool.kwargs[0]["_job_id"] == f"scan:{aid}"


async def test_enqueue_dedup_logs_when_job_none() -> None:
    pool = _FakePool(job=None)  # bereits vorhandener Job → None
    await ArqScanQueue(pool).enqueue(uuid.uuid4())
    assert pool.calls  # kein Fehler, nur Log


def test_scan_queue_from_pool() -> None:
    assert scan_queue_from_pool(None) is None
    assert isinstance(scan_queue_from_pool(_FakePool()), ArqScanQueue)  # type: ignore[arg-type]
