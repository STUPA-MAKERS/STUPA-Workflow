"""Protokoll-Render-Enqueue-Abstraktion (arq) — ``finalize`` blockiert nie (T-22).

Nach dem Statuswechsel ``draft → rendering`` legt der Router nur einen
``render_protocol``-Job in Redis (gleicher arq-Pool wie Mail/PDF); der Worker
rendert + versendet async. **Bewusst ohne** ``_job_id``: nach einem
``rendering → draft``-Rollback (Render dauerhaft fehlgeschlagen) muss ein erneutes
finalize einen frischen Job anlegen — eine idempotente Job-Id würde gegen das noch
gespeicherte Ergebnis des alten Jobs koaleszieren und nie wieder rendern.
Doppel-Enqueue verhindert stattdessen der Status selbst (``start_finalize``
enqueued nur beim Wechsel von ``draft``); ein doppelt laufender Job ist harmlos
(``finalize`` ist idempotent, Mail-Versand dedupet über den Idempotenz-Key).
Fehlt Redis (DEV/Contract-CI), ist die Queue ``None`` → der Router rendert synchron
als Fallback (kein Hänger in ``rendering``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from arq.connections import ArqRedis

logger = logging.getLogger("app.protocol")

PROTOCOL_RENDER_TASK_NAME = "render_protocol"


class ProtocolRenderQueue(Protocol):
    """Enqueue-Schnittstelle (vom Router genutzt)."""

    async def enqueue(self, protocol_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqProtocolRenderQueue:
    """arq-gestützte Queue für ``render_protocol``-Jobs."""

    pool: object  # arq.ArqRedis (lose typisiert: kein arq-Import in der API-Fläche)

    async def enqueue(self, protocol_id: UUID) -> None:
        await self.pool.enqueue_job(  # type: ignore[attr-defined]
            PROTOCOL_RENDER_TASK_NAME, str(protocol_id)
        )


def protocol_render_queue_from_pool(
    pool: ArqRedis | None,
) -> ProtocolRenderQueue | None:
    """Pool → :class:`ProtocolRenderQueue` (oder ``None``, wenn kein Pool)."""
    return ArqProtocolRenderQueue(pool) if pool is not None else None
