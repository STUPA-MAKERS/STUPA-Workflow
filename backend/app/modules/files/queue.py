"""Scan enqueue abstraction (arq) — upload never blocks on ClamAV.

After upload the service only puts a ``scan_attachment`` job in Redis (same arq pool as
mail dispatch); the worker scans async and writes the result back. Job id =
``scan:<attachment_id>`` → duplicate enqueues of the same attachment coalesce
(idempotent). Without Redis (DEV/contract CI) the queue is ``None`` → callers log + skip
(file stays quarantined, no API block).
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
    """Enqueue interface (used by the service)."""

    async def enqueue(self, attachment_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqScanQueue:
    """arq-backed queue: ``scan_attachment`` job with an idempotent job id."""

    pool: object  # arq.ArqRedis (loosely typed: no arq import in the API surface)

    async def enqueue(self, attachment_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            SCAN_TASK_NAME, str(attachment_id), _job_id=f"scan:{attachment_id}"
        )
        if job is None:
            logger.info("scan enqueue deduped (attachment=%s)", attachment_id)


def scan_queue_from_pool(pool: ArqRedis | None) -> ScanQueue | None:
    """Pool → :class:`ScanQueue` (or ``None`` if no pool)."""
    return ArqScanQueue(pool) if pool is not None else None
