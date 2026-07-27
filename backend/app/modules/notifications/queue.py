"""Mail enqueue abstraction (arq) with an idempotent job key.

`ArqMailQueue` puts a `send_mail` job into Redis. The arq `_job_id` is the
`MailMessage.idempotency_key`, so duplicate enqueues of the same mail collapse
into one job. `DirectMailQueue` sends inline for tests and dev without Redis.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

from app.modules.notifications.mail import MailMessage, MailSender

logger = logging.getLogger("app.mail")

MAIL_TASK_NAME = "send_mail"

# Cap on the in-memory dedup cache of `DirectMailQueue`. The cache drops the
# oldest keys first (LRU). Production dedups through the arq `_job_id`, not
# through this cache.
DIRECT_QUEUE_SEEN_MAX = 4096


class MailQueue(Protocol):
    """Enqueue interface used by the service."""

    async def enqueue(self, msg: MailMessage) -> None: ...


@dataclass(slots=True)
class ArqMailQueue:
    """arq-backed queue: `send_mail` job with an idempotent job id."""

    pool: object  # arq.ArqRedis, loosely typed to keep arq out of the API surface

    async def enqueue(self, msg: MailMessage) -> None:
        # The `_job_id` is the idempotency key. arq drops an already-present job
        # id and returns None, so there is no double send.
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            MAIL_TASK_NAME, msg.to_payload(), _job_id=msg.idempotency_key or None
        )
        if job is None:
            logger.info("mail enqueue deduped (key=%s)", msg.idempotency_key)


@dataclass(slots=True)
class DirectMailQueue:
    """Inline send for tests and dev: call the sender directly, without Redis.

    The queue keeps its own idempotency cache and skips an already-seen key.
    The cache holds at most `max_seen` entries and drops the oldest key first.
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
