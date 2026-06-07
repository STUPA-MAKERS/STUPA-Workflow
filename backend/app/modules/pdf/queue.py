"""Render-Enqueue-Abstraktion (arq) — die API rendert nie selbst (T-20).

Nach dem Anlegen der ``render_job``-Zeile legt der Service nur einen ``render_pdf``-Job
in Redis (gleicher arq-Pool wie Mail/Scan); der Worker rendert async (202-Pfad,
flows §6). Job-Id = ``render:<job_id>`` → ein erneuter Enqueue desselben Jobs
koalesziert (idempotent). Fehlt Redis (DEV/Contract-CI), ist die Queue ``None`` → der
Aufrufer hält den Job auf ``pending`` + loggt (kein API-Block, kein Crash).
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
    """Enqueue-Schnittstelle (vom Service genutzt)."""

    async def enqueue(self, job_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqRenderQueue:
    """arq-gestützte Queue: ``render_pdf``-Job mit idempotenter Job-Id."""

    pool: object  # arq.ArqRedis (lose typisiert: kein arq-Import in der API-Fläche)

    async def enqueue(self, job_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            RENDER_TASK_NAME, str(job_id), _job_id=f"render:{job_id}"
        )
        if job is None:
            logger.info("render enqueue deduped (job=%s)", job_id)


def render_queue_from_pool(pool: ArqRedis | None) -> RenderQueue | None:
    """Pool → :class:`RenderQueue` (oder ``None``, wenn kein Pool)."""
    return ArqRenderQueue(pool) if pool is not None else None
