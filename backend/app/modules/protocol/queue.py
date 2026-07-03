"""Protocol-render enqueue abstraction (arq) — ``finalize`` never blocks.

After ``draft → rendering`` the router only enqueues a ``render_protocol`` job;
the worker renders and mails async. Deliberately no ``_job_id``: after a
``rendering → draft`` rollback a fresh finalize must enqueue a fresh job — an
idempotent job id would coalesce against the old job's stored result and never
render again. Double-enqueue is prevented by the status itself
(``start_finalize`` only enqueues when leaving ``draft``); a duplicate running
job is harmless (``finalize`` is idempotent, mail dedupes via idempotency key).
Without Redis (dev/contract CI) the queue is ``None`` and the router renders
synchronously as fallback (no hang in ``rendering``).
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
    """Enqueue interface used by the router."""

    async def enqueue(self, protocol_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqProtocolRenderQueue:
    """arq-backed queue for ``render_protocol`` jobs."""

    pool: object  # arq.ArqRedis (loosely typed: no arq import in the API surface)

    async def enqueue(self, protocol_id: UUID) -> None:
        await self.pool.enqueue_job(  # type: ignore[attr-defined]
            PROTOCOL_RENDER_TASK_NAME, str(protocol_id)
        )


def protocol_render_queue_from_pool(
    pool: ArqRedis | None,
) -> ProtocolRenderQueue | None:
    """Wrap a pool as :class:`ProtocolRenderQueue` (``None`` if no pool)."""
    return ArqProtocolRenderQueue(pool) if pool is not None else None
