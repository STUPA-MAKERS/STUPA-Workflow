"""Scan enqueue abstraction over arq. An upload never blocks on ClamAV.

After an upload the service only puts a ``scan_attachment`` job into Redis. It uses the
same arq pool as the mail dispatch. The worker scans the file asynchronously and writes
the result back. The job id is ``scan:<attachment_id>``, so two enqueues for the same
attachment coalesce into one job.

Without Redis (development or contract CI) the queue is ``None``. The caller then logs
and skips the enqueue. The file stays quarantined and the API does not block.
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
    """Enqueue interface that the service uses."""

    async def enqueue(self, attachment_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqScanQueue:
    """Queue on top of arq: a ``scan_attachment`` job with an idempotent job id."""

    pool: object  # arq.ArqRedis, typed loosely to keep arq out of the API surface

    async def enqueue(self, attachment_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            SCAN_TASK_NAME, str(attachment_id), _job_id=f"scan:{attachment_id}"
        )
        if job is None:
            logger.info("scan enqueue deduped (attachment=%s)", attachment_id)


def scan_queue_from_pool(pool: ArqRedis | None) -> ScanQueue | None:
    """Build a ``ScanQueue`` from the pool, or return ``None`` when there is no pool."""
    return ArqScanQueue(pool) if pool is not None else None
