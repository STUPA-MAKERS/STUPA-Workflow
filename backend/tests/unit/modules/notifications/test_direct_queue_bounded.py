"""DirectMailQueue: gebundener In-Memory-Dedup-Cache (AUD-074)."""

from __future__ import annotations

import pytest

from app.modules.notifications.mail import MailMessage, MailSender
from app.modules.notifications.queue import DirectMailQueue

pytestmark = pytest.mark.asyncio


class _CountingSender(MailSender):
    def __init__(self) -> None:
        self.sent: list[MailMessage] = []

    async def send(self, msg: MailMessage) -> None:
        self.sent.append(msg)


def _msg(key: str) -> MailMessage:
    return MailMessage(to=("a@x.de",), subject="s", text="b", idempotency_key=key)


async def test_seen_cache_is_bounded() -> None:
    sender = _CountingSender()
    q = DirectMailQueue(sender, max_seen=3)
    for i in range(10):
        await q.enqueue(_msg(f"k{i}"))
    # Alle 10 distinkten Keys werden versendet ...
    assert len(sender.sent) == 10
    # ... aber der Cache wächst nicht unbegrenzt.
    assert len(q._seen) == 3
    # Nur die jüngsten Keys bleiben.
    assert list(q._seen) == ["k7", "k8", "k9"]


async def test_recent_key_still_deduped() -> None:
    sender = _CountingSender()
    q = DirectMailQueue(sender, max_seen=3)
    await q.enqueue(_msg("k0"))
    await q.enqueue(_msg("k0"))  # gleicher Key, noch im Cache -> dedupliziert
    assert len(sender.sent) == 1
    assert list(q._seen) == ["k0"]


async def test_evicted_key_resends() -> None:
    sender = _CountingSender()
    q = DirectMailQueue(sender, max_seen=2)
    await q.enqueue(_msg("k0"))
    await q.enqueue(_msg("k1"))
    await q.enqueue(_msg("k2"))  # verdrängt k0
    await q.enqueue(_msg("k0"))  # k0 nicht mehr im Cache -> erneut versendet
    assert len(sender.sent) == 4
