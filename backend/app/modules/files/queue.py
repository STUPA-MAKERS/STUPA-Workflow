"""Scan-Enqueue-Abstraktion (arq) — Upload blockiert nie auf ClamAV.

Der Service legt nach dem Upload nur einen ``scan_attachment``-Job in Redis (gleicher
arq-Pool wie der Mail-Versand, T-18); der Worker scannt async und schreibt das Ergebnis
zurück. Job-Id = ``scan:<attachment_id>`` → doppelte Enqueues desselben Anhangs
koaleszieren (idempotent). Fehlt Redis (DEV/Contract-CI), ist die Queue ``None`` →
Aufrufer loggen + überspringen (Datei bleibt in Quarantäne, kein API-Block).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from arq.connections import ArqRedis

logger = logging.getLogger("app.files")

SCAN_TASK_NAME = "scan_attachment"


class ScanQueue(Protocol):
    """Enqueue-Schnittstelle (vom Service genutzt)."""

    async def enqueue(self, attachment_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqScanQueue:
    """arq-gestützte Queue: ``scan_attachment``-Job mit idempotenter Job-Id."""

    pool: object  # arq.ArqRedis (lose typisiert: kein arq-Import in der API-Fläche)

    async def enqueue(self, attachment_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            SCAN_TASK_NAME, str(attachment_id), _job_id=f"scan:{attachment_id}"
        )
        if job is None:
            logger.info("scan enqueue deduped (attachment=%s)", attachment_id)


def scan_queue_from_pool(pool: ArqRedis | None) -> ScanQueue | None:
    """Pool → :class:`ScanQueue` (oder ``None``, wenn kein Pool)."""
    return ArqScanQueue(pool) if pool is not None else None
