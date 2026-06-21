"""Versand-Enqueue-Abstraktion (arq) + idempotenter Job-Key.

Der Service kennt nur `MailQueue.enqueue` — nicht *wie* versendet wird. Produktiv
legt `ArqMailQueue` einen `send_mail`-Job in Redis (Worker sendet async, blockiert
die API nicht). Der arq-`_job_id` = `MailMessage.idempotency_key` → doppelte
Enqueues desselben Mails koaleszieren (idempotent). `DirectMailQueue` versendet
inline (Tests/DEV ohne Redis).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

from app.modules.notifications.mail import MailMessage, MailSender

logger = logging.getLogger("app.mail")

MAIL_TASK_NAME = "send_mail"

# Obergrenze des In-Memory-Dedup-Caches von `DirectMailQueue`. Begrenzt den
# Speicher einer (eigentlich nur für Tests/DEV gedachten) langlebigen Instanz;
# älteste Keys werden FIFO/LRU verdrängt. Produktiv dedupliziert `ArqMailQueue`
# über die arq-`_job_id`, nicht über diesen Cache.
DIRECT_QUEUE_SEEN_MAX = 4096


class MailQueue(Protocol):
    """Enqueue-Schnittstelle (vom Service genutzt)."""

    async def enqueue(self, msg: MailMessage) -> None: ...


@dataclass(slots=True)
class ArqMailQueue:
    """arq-gestützte Queue: `send_mail`-Job mit idempotenter Job-Id."""

    pool: object  # arq.ArqRedis (lose typisiert: kein arq-Import in der API-Fläche)

    async def enqueue(self, msg: MailMessage) -> None:
        # `_job_id` = Idempotenz-Key: arq verwirft ein bereits vorhandenes Job-Id
        # (gibt None zurück) → kein Doppelversand.
        job = await self.pool.enqueue_job(  # type: ignore[attr-defined]
            MAIL_TASK_NAME, msg.to_payload(), _job_id=msg.idempotency_key or None
        )
        if job is None:
            logger.info("mail enqueue deduped (key=%s)", msg.idempotency_key)


@dataclass(slots=True)
class DirectMailQueue:
    """Inline-Versand (Tests/DEV): ruft den Sender direkt, kein Redis.

    Eigene Idempotenz: schon gesehene Keys werden übersprungen. Der Cache ist auf
    `max_seen` Einträge begrenzt (LRU-Verdrängung der ältesten Keys), damit eine
    langlebige Instanz nicht unbegrenzt wächst.
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
