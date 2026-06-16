"""arq-Enqueue-Abstraktion (T-19): idempotenter Job-Key + Dedup + None-Pool."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.webhooks.queue import (
    ArqWebhookQueue,
    job_id_for,
    webhook_queue_from_pool,
)


class _Pool:
    def __init__(self, *, returns: object) -> None:
        self.returns = returns
        self.calls: list[tuple[str, str, str]] = []

    async def enqueue_job(self, name: str, arg: str, *, _job_id: str) -> object:
        self.calls.append((name, arg, _job_id))
        return self.returns


def test_job_id_for() -> None:
    did = uuid.uuid4()
    assert job_id_for(did) == f"webhook:{did}"


async def test_enqueue_passes_idempotent_job_id() -> None:
    did = uuid.uuid4()
    pool = _Pool(returns=object())
    await ArqWebhookQueue(pool).enqueue(did)
    assert pool.calls == [("deliver_webhook", str(did), f"webhook:{did}")]


async def test_enqueue_deduped_when_job_exists() -> None:
    did = uuid.uuid4()
    pool = _Pool(returns=None)  # arq: bereits vorhandener Job → None
    await ArqWebhookQueue(pool).enqueue(did)
    assert pool.calls[0][0] == "deliver_webhook"


def test_queue_from_pool() -> None:
    assert webhook_queue_from_pool(None) is None
    pool: Any = _Pool(returns=object())
    assert isinstance(webhook_queue_from_pool(pool), ArqWebhookQueue)
