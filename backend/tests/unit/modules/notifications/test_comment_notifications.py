"""Tests der Kommentar-Benachrichtigungen (#4-1) — Service/Resolver gefaked."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.notifications.comments as mod
from app.modules.notifications.comments import send_comment_notifications
from app.settings import load_settings
from tests._support.notifications_fakes import FakeQueue, FakeResolver, FakeSession

SETTINGS = load_settings()


class _FakeService:
    """Ersetzt NotificationService: kein Template in DB, Enqueue wird gesammelt."""

    last: _FakeService | None = None

    def __init__(self, session: Any, *, queue: Any, settings: Any) -> None:
        self.session = session
        self.queue = queue
        self.settings = settings
        self.resolver = FakeResolver(["applicant@x.de"])
        self.enqueued: list[Any] = []
        _FakeService.last = self

    async def _get_template_by_key(self, key: str) -> None:
        return None

    def _layout_html(self, rendered: Any, reason: str) -> str:
        return f"<html>{reason}</html>"

    async def _enqueue(self, msg: Any) -> bool:
        self.enqueued.append(msg)
        return True


@pytest.fixture(autouse=True)
def _patch_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "NotificationService", _FakeService)


def _app_row(title: str | None = "Beamer") -> list[Any]:
    data = {"title": title} if title else {}
    return [(data, None, None)]


async def test_principal_public_comment_mails_applicant() -> None:
    # scalars: 1× Präferenz-Filter (keine Abwahlen).
    session = cast(AsyncSession, FakeSession(executes=[_app_row()], scalars=[[]]))
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="principal",
        visibility="public",
        body="Bitte Angebot nachreichen.",
    )
    assert sent == 1
    svc = _FakeService.last
    assert svc is not None and len(svc.enqueued) == 1
    msg = svc.enqueued[0]
    assert msg.to == ("applicant@x.de",)
    assert "Beamer" in msg.subject
    assert "Bitte Angebot nachreichen." in msg.text
    assert msg.html == "<html>comment</html>"


async def test_internal_comment_sends_nothing() -> None:
    session = cast(AsyncSession, FakeSession(executes=[_app_row()]))
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="principal",
        visibility="internal",
        body="intern",
    )
    assert sent == 0
    assert _FakeService.last is not None
    assert _FakeService.last.enqueued == []


async def test_applicant_comment_mails_actionable_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_actionable(session: Any, *, state: Any, gremium_id: Any) -> list[str]:
        return ["team@x.de", "vorstand@x.de"]

    monkeypatch.setattr(mod, "actionable_principal_emails", fake_actionable)
    session = cast(AsyncSession, FakeSession(executes=[_app_row()], scalars=[[]]))
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="applicant",
        visibility="public",
        body="Wann wird entschieden?",
    )
    assert sent == 1
    svc = _FakeService.last
    assert svc is not None
    msg = svc.enqueued[0]
    assert msg.to == ("team@x.de", "vorstand@x.de")
    assert "Beamer" in msg.subject
    assert "Wann wird entschieden?" in msg.text


async def test_preference_optout_blocks_comment_mail() -> None:
    # Präferenz-Filter liefert die Antragsteller-Adresse als abgewählt.
    session = cast(AsyncSession, FakeSession(executes=[_app_row()], scalars=[["applicant@x.de"]]))
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="principal",
        visibility="public",
        body="Hallo",
    )
    assert sent == 0
