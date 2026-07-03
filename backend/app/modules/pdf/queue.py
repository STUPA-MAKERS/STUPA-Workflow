"""Render-enqueue abstraction (arq) — the API never renders itself.

After creating the ``render_job`` row the service only puts a ``render_pdf`` job in
Redis (same arq pool as mail/scan); the worker renders async. Job id =
``render:<job_id>`` so re-enqueuing the same job coalesces (idempotent). Without Redis
(dev/contract CI) the queue is ``None``, so the caller leaves the job ``pending`` and
logs (no API block, no crash).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from arq.connections import ArqRedis

logger = logging.getLogger("app.pdf")

RENDER_TASK_NAME = "render_pdf"


class RenderQueue(Protocol):
    """Enqueue interface used by the service."""

    async def enqueue(self, job_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqRenderQueue:
    """arq-backed queue: ``render_pdf`` job with an idempotent job id."""

    pool: object  # arq.ArqRedis (loosely typed: no arq import on the API surface)

    async def enqueue(self, job_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            RENDER_TASK_NAME, str(job_id), _job_id=f"render:{job_id}"
        )
        if job is None:
            logger.info("render enqueue deduped (job=%s)", job_id)


def render_queue_from_pool(pool: ArqRedis | None) -> RenderQueue | None:
    """Pool → ``RenderQueue`` (or ``None`` when there is no pool)."""
    return ArqRenderQueue(pool) if pool is not None else None
