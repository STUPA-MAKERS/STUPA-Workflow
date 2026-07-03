"""Enqueue abstraction (arq) for webhook deliveries.

:class:`ArqWebhookQueue` enqueues a ``deliver_webhook`` job in Redis; the ``_job_id``
= ``webhook:<delivery_id>``, so duplicate enqueues of the same delivery coalesce.
Without Redis the queue is ``None`` and callers skip (delivery stays ``pending``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from arq.connections import ArqRedis

logger = logging.getLogger("app.webhooks")

WEBHOOK_TASK_NAME = "deliver_webhook"


def job_id_for(delivery_id: UUID) -> str:
    """Stable arq job key per delivery (dedup on enqueue)."""
    return f"webhook:{delivery_id}"


class WebhookQueue(Protocol):
    """Enqueue interface used by the service."""

    async def enqueue(self, delivery_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqWebhookQueue:
    """arq-backed queue: ``deliver_webhook`` job with an idempotent job id."""

    pool: object  # arq.ArqRedis (loosely typed: no arq import in the API surface)

    async def enqueue(self, delivery_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            WEBHOOK_TASK_NAME, str(delivery_id), _job_id=job_id_for(delivery_id)
        )
        if job is None:
            logger.info("webhook enqueue deduped (delivery=%s)", delivery_id)


def webhook_queue_from_pool(pool: ArqRedis | None) -> WebhookQueue | None:
    """Pool -> :class:`WebhookQueue` (or ``None`` when there is no pool)."""
    return ArqWebhookQueue(pool) if pool is not None else None
