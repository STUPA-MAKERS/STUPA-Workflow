"""Versand-Enqueue-Abstraktion (arq) + idempotenter Job-Key.

Der Service kennt nur `MailQueue.enqueue` — nicht *wie* versendet wird. Produktiv
legt `ArqMailQueue` einen `send_mail`-Job in Redis (Worker sendet async, blockiert
die API nicht). Der arq-`_job_id` = `MailMessage.idempotency_key` → doppelte
Enqueues desselben Mails koaleszieren (idempotent). `DirectMailQueue` versendet
inline (Tests/DEV ohne Redis).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.modules.notifications.mail import MailMessage, MailSender

logger = logging.getLogger("app.mail")

MAIL_TASK_NAME = "send_mail"


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

    Eigene Idempotenz: schon gesehene Keys werden übersprungen.
    """

    sender: MailSender
    _seen: set[str] | None = None

    async def enqueue(self, msg: MailMessage) -> None:
        seen = self._seen if self._seen is not None else set()
        self._seen = seen
        if msg.idempotency_key and msg.idempotency_key in seen:
            logger.info("mail enqueue deduped (key=%s)", msg.idempotency_key)
            return
        if msg.idempotency_key:
            seen.add(msg.idempotency_key)
        await self.sender.send(msg)
