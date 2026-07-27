"""Enqueue abstraction for the protocol render (arq), so `finalize` never blocks.

After the step from `draft` to `rendering` the router only enqueues a
`render_protocol` job. The worker renders and mails asynchronously.

The queue passes no `_job_id` on purpose. After a rollback from `rendering` to
`draft`, a new finalize must enqueue a new job. An idempotent job id would
coalesce with the stored result of the old job and never render again.

The status itself prevents a double enqueue, because `start_finalize` only
enqueues when it leaves `draft`. A second running job does no harm, because
`finalize` is idempotent and the mail dedupes through an idempotency key.

Without Redis, in dev and in contract CI, the queue is `None`. The router then
renders synchronously as a fallback, so a protocol never hangs in `rendering`.
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
    """Enqueue interface for the router."""

    async def enqueue(self, protocol_id: UUID) -> None: ...


@dataclass(slots=True)
class ArqProtocolRenderQueue:
    """Queue for `render_protocol` jobs, backed by arq."""

    pool: object  # arq.ArqRedis, typed loosely to keep arq out of the API surface

    async def enqueue(self, protocol_id: UUID) -> None:
        await self.pool.enqueue_job(  # type: ignore[attr-defined]
            PROTOCOL_RENDER_TASK_NAME, str(protocol_id)
        )


def protocol_render_queue_from_pool(
    pool: ArqRedis | None,
) -> ProtocolRenderQueue | None:
    """Wrap a pool as a `ProtocolRenderQueue`, or return `None` without a pool."""
    return ArqProtocolRenderQueue(pool) if pool is not None else None
