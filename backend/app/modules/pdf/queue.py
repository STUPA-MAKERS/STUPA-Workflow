"""Render-enqueue abstraction (arq) — the API never renders itself.

After it creates the ``render_job`` row, the service only puts a ``render_pdf`` job in
Redis. It uses the same arq pool as mail and scan. The worker then renders async. The
job id is ``render:<job_id>``, so a second enqueue of the same job coalesces and stays
idempotent. Without Redis (dev and contract CI) the queue is ``None``. The caller then
leaves the job ``pending`` and writes a log line. The API neither blocks nor crashes.
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
    """Enqueue interface for the service."""

    async def enqueue(self, job_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqRenderQueue:
    """arq-backed queue: ``render_pdf`` job with an idempotent job id."""

    pool: object  # arq.ArqRedis, loosely typed to keep the arq import off the API surface

    async def enqueue(self, job_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            RENDER_TASK_NAME, str(job_id), _job_id=f"render:{job_id}"
        )
        if job is None:
            logger.info("render enqueue deduped (job=%s)", job_id)


def render_queue_from_pool(pool: ArqRedis | None) -> RenderQueue | None:
    """Pool → ``RenderQueue`` (or ``None`` when there is no pool)."""
    return ArqRenderQueue(pool) if pool is not None else None
