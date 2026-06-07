"""Versand-Enqueue-Abstraktion (arq) für Webhook-Deliveries.

Der Service kennt nur :meth:`WebhookQueue.enqueue` — nicht *wie* zugestellt wird.
Produktiv legt :class:`ArqWebhookQueue` einen ``deliver_webhook``-Job in Redis (gleicher
Pool wie Mail/Scan); der Worker stellt async zu. Der ``_job_id`` =
``webhook:<delivery_id>`` → doppelte Enqueues derselben Delivery koaleszieren
(idempotent). Fehlt Redis (DEV/Contract-CI), ist die Queue ``None`` → Aufrufer loggen
+ überspringen (Delivery bleibt ``pending``, kein API-Block).
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
    """Stabiler arq-Job-Key je Delivery (Dedup beim Enqueue)."""
    return f"webhook:{delivery_id}"


class WebhookQueue(Protocol):
    """Enqueue-Schnittstelle (vom Service genutzt)."""

    async def enqueue(self, delivery_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqWebhookQueue:
    """arq-gestützte Queue: ``deliver_webhook``-Job mit idempotenter Job-Id."""

    pool: object  # arq.ArqRedis (lose typisiert: kein arq-Import in der API-Fläche)

    async def enqueue(self, delivery_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            WEBHOOK_TASK_NAME, str(delivery_id), _job_id=job_id_for(delivery_id)
        )
        if job is None:
            logger.info("webhook enqueue deduped (delivery=%s)", delivery_id)


def webhook_queue_from_pool(pool: ArqRedis | None) -> WebhookQueue | None:
    """Pool → :class:`WebhookQueue` (oder ``None``, wenn kein Pool)."""
    return ArqWebhookQueue(pool) if pool is not None else None
