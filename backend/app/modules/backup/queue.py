"""Backup-enqueue abstraction (arq) — the API never dumps or restores itself.

The routes create the catalogue row and then put one job in Redis. It is the same arq
pool that mail, scan and render use. Without Redis (development, contract CI) the queue
is ``None``; the route then leaves the row ``pending`` and says so, rather than blocking
a request on a job that takes minutes.

The create job id is ``backup:<id>``, so a double click coalesces into one archive. The
restore job carries NO such id: a restore is deliberate and the route already refuses a
second one while any restore is in flight.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from arq.connections import ArqRedis

logger = logging.getLogger("app.backup")

CREATE_TASK_NAME = "create_backup"
RESTORE_TASK_NAME = "restore_backup"


class BackupQueue(Protocol):
    """Enqueue interface for the routes."""

    async def enqueue_create(self, backup_id: UUID) -> None: ...

    async def enqueue_restore(self, backup_id: UUID, actor: str | None) -> None: ...


@dataclass(slots=True)
class ArqBackupQueue:
    """arq-backed queue for the two backup tasks."""

    pool: object  # arq.ArqRedis, loosely typed to keep the arq import off the API surface

    async def enqueue_create(self, backup_id: UUID) -> None:
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            CREATE_TASK_NAME, str(backup_id), _job_id=f"backup:{backup_id}"
        )
        if job is None:
            logger.info("backup enqueue deduped (backup=%s)", backup_id)

    async def enqueue_restore(self, backup_id: UUID, actor: str | None) -> None:
        await self.pool.enqueue_job(  # type: ignore[attr-defined]
            RESTORE_TASK_NAME, str(backup_id), actor
        )


def backup_queue_from_pool(pool: ArqRedis | None) -> BackupQueue | None:
    """Pool → ``BackupQueue`` (or ``None`` when there is no pool)."""
    return ArqBackupQueue(pool) if pool is not None else None
