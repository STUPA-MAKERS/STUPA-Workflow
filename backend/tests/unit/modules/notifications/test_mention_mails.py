"""Unit tests of the mention mail wrappers and the router senders (no database).

The integration suite (``test_comment_mentions.py``) covers the recipients, the
opt-out, the texts and the links against a real schema.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.applications import router as app_router
from app.modules.notifications import mentions as mails
from app.modules.tickets import router as ticket_router
from app.settings import load_settings

SETTINGS = load_settings()
NOTE = uuid.UUID(int=7)
ADA = uuid.UUID(int=8)


class _Maker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def __call__(self) -> _Maker:
        if self.fail:
            raise RuntimeError("no database")
        return self

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_a: object) -> None:
        return None


async def test_the_wrappers_send_in_an_own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    async def _send(_session: object, **kw: Any) -> int:
        seen.append(kw)
        return 2

    monkeypatch.setattr(mails, "send_comment_mentions", _send)
    monkeypatch.setattr(mails, "send_ticket_mentions", _send)
    maker: Any = _Maker()
    assert (
        await mails.notify_comment_mentions(
            queue=None,
            settings=SETTINGS,
            comment_id=NOTE,
            recipients=[ADA],
            actor_sub="me",
            sessionmaker=maker,
        )
        == 2
    )
    assert (
        await mails.notify_ticket_mentions(
            queue=None, settings=SETTINGS, note_id=NOTE, recipients=[ADA], sessionmaker=maker
        )
        == 2
    )
    assert seen[0]["comment_id"] == NOTE and seen[0]["actor_sub"] == "me"
    assert seen[1]["note_id"] == NOTE and seen[1]["recipients"] == [ADA]


async def test_a_failure_never_breaks_the_write() -> None:
    maker: Any = _Maker(fail=True)
    assert (
        await mails.notify_comment_mentions(
            queue=None,
            settings=SETTINGS,
            comment_id=NOTE,
            recipients=[ADA],
            actor_sub="me",
            sessionmaker=maker,
        )
        == 0
    )
    assert (
        await mails.notify_ticket_mentions(
            queue=None, settings=SETTINGS, note_id=NOTE, recipients=[ADA], sessionmaker=maker
        )
        == 0
    )


async def test_the_router_senders_pass_the_queue_of_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def _notify(**kw: Any) -> int:
        seen.append(kw)
        return 1

    monkeypatch.setattr(app_router, "notify_comment_mentions", _notify)
    monkeypatch.setattr(ticket_router, "notify_ticket_mentions", _notify)
    await app_router.get_mention_mail_sender()(SETTINGS, NOTE, [ADA], "me", None)
    await ticket_router.get_mention_mail_sender()(SETTINGS, NOTE, [ADA], None)
    assert seen[0]["comment_id"] == NOTE and seen[0]["actor_sub"] == "me"
    assert seen[1]["note_id"] == NOTE and seen[1]["recipients"] == [ADA]
    assert seen[0]["queue"] is None and seen[1]["queue"] is None
