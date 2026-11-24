"""Mail enqueue abstraction (arq) with an idempotent job key.

`ArqMailQueue` puts a `send_mail` job into Redis. The arq `_job_id` is the
`MailMessage.idempotency_key`, so duplicate enqueues of the same mail collapse
into one job. `DirectMailQueue` sends inline for tests and dev without Redis.

A queue that also takes push jobs implements `PushQueue`: `ArqMailQueue` puts a
`send_push` job per device into the same Redis. `DirectMailQueue` drops them, because dev
and test have no push service to send to.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.modules.notifications.mail import MailMessage, MailSender

if TYPE_CHECKING:
    from app.modules.notifications.push_service import PushJob

logger = logging.getLogger("app.mail")

MAIL_TASK_NAME = "send_mail"
PUSH_TASK_NAME = "send_push"

#: Cap of the in-memory dedup cache of ``DirectMailQueue`` (LRU). Production dedups
#: through the arq ``_job_id``, not through this cache.
DIRECT_QUEUE_SEEN_MAX = 4096


class MailQueue(Protocol):
    """Enqueue interface used by the service."""

    async def enqueue(self, msg: MailMessage) -> None:
        """Enqueue one mail."""
        ...


@runtime_checkable
class PushQueue(Protocol):
    """A queue that also takes push jobs (one per device)."""

    async def enqueue_push(self, job: PushJob) -> None:
        """Enqueue one push job."""
        ...


@dataclass(frozen=True, slots=True)
class ArqMailQueue:
    """arq-backed queue: `send_mail` job with an idempotent job id.

    ``pool`` is an ``arq.ArqRedis``, typed loosely to keep arq out of the API surface.
    """

    pool: object

    async def enqueue(self, msg: MailMessage) -> None:
        """Enqueue a ``send_mail`` job keyed by the idempotency key.

        arq drops a job whose id is already present and returns None, so there is no
        double send.
        """
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            MAIL_TASK_NAME, msg.to_payload(), _job_id=msg.idempotency_key or None
        )
        if job is None:
            logger.info("mail enqueue deduped (key=%s)", msg.idempotency_key)

    async def enqueue_push(self, job: PushJob) -> None:
        """Enqueue a ``send_push`` job; the job id drops a second push of one event."""
        queued = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            PUSH_TASK_NAME, job.to_payload(), _job_id=job.job_id or None
        )
        if queued is None:
            logger.info("push enqueue deduped")


@dataclass(frozen=True, slots=True)
class DirectMailQueue:
    """Inline send for tests and dev: call the sender directly, without Redis.

    The queue keeps its own idempotency cache and skips an already-seen key.
    The cache holds at most `max_seen` entries and drops the oldest key first.
    """

    sender: MailSender
    max_seen: int = DIRECT_QUEUE_SEEN_MAX
    _seen: OrderedDict[str, None] = field(default_factory=OrderedDict)

    async def enqueue(self, msg: MailMessage) -> None:
        """Send the mail at once unless its key was already seen."""
        key = msg.idempotency_key
        if key and key in self._seen:
            self._seen.move_to_end(key)
            logger.info("mail enqueue deduped (key=%s)", key)
            return
        if key:
            self._seen[key] = None
            while len(self._seen) > self.max_seen:
                self._seen.popitem(last=False)
        await self.sender.send(msg)

    async def enqueue_push(self, job: PushJob) -> None:
        """Drop the push job; dev and test have no push service to send to."""
        logger.info("push dropped without a push service (job=%s)", job.job_id)
