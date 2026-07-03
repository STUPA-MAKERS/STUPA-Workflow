"""Mail enqueue abstraction (arq) with an idempotent job key.

`ArqMailQueue` enqueues a `send_mail` job in Redis; the arq `_job_id` =
`MailMessage.idempotency_key`, so duplicate enqueues of the same mail coalesce.
`DirectMailQueue` sends inline (tests/dev without Redis).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

from app.modules.notifications.mail import MailMessage, MailSender

logger = logging.getLogger("app.mail")

MAIL_TASK_NAME = "send_mail"

# Cap on the in-memory dedup cache of `DirectMailQueue`; oldest keys are evicted
# LRU. Production dedups via the arq `_job_id`, not this cache.
DIRECT_QUEUE_SEEN_MAX = 4096


class MailQueue(Protocol):
    """Enqueue interface used by the service."""

    async def enqueue(self, msg: MailMessage) -> None: ...


@dataclass(slots=True)
class ArqMailQueue:
    """arq-backed queue: `send_mail` job with an idempotent job id."""

    pool: object  # arq.ArqRedis (loosely typed: no arq import in the API surface)

    async def enqueue(self, msg: MailMessage) -> None:
        # `_job_id` = idempotency key: arq drops an already-present job id
        # (returns None), so no double send.
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            MAIL_TASK_NAME, msg.to_payload(), _job_id=msg.idempotency_key or None
        )
        if job is None:
            logger.info("mail enqueue deduped (key=%s)", msg.idempotency_key)


@dataclass(slots=True)
class DirectMailQueue:
    """Inline send (tests/dev): calls the sender directly, no Redis.

    Own idempotency: already-seen keys are skipped. The cache is capped at
    `max_seen` entries (LRU eviction of the oldest keys).
    """

    sender: MailSender
    max_seen: int = DIRECT_QUEUE_SEEN_MAX
    _seen: OrderedDict[str, None] = field(default_factory=OrderedDict)

    async def enqueue(self, msg: MailMessage) -> None:
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
