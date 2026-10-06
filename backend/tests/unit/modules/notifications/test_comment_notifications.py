"""Comment notification tests (#4-1) with a fake service and a fake resolver."""

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
    """Replace NotificationService: no template in the database, collect each enqueue."""

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
    # Reset the class attribute, so a test never reads the service of the test before.
    _FakeService.last = None
    monkeypatch.setattr(mod, "NotificationService", _FakeService)


def _app_row(title: str | None = "Beamer", gremium_id: uuid.UUID | None = None) -> list[Any]:
    """Return the `(data, current_state_id, gremium_id)` row of the application."""
    data = {"title": title} if title else {}
    return [(data, None, gremium_id)]


async def test_principal_public_comment_mails_applicant() -> None:
    # scalars: one preference filter query with no opt-outs.
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


async def test_principal_public_comment_uses_the_application_language() -> None:
    """The applicant reads the comment mail in the language of their application."""
    # executes: the application row, then the (lang, gremium_id) row of that
    # application. scalars: the preference filter with no opt-outs.
    session = cast(
        AsyncSession,
        FakeSession(executes=[_app_row(), [("en", None)]], scalars=[[]]),
    )
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="principal",
        visibility="public",
        body="Please add the quote.",
    )
    assert sent == 1
    svc = _FakeService.last
    assert svc is not None
    msg = svc.enqueued[0]
    assert msg.subject == 'New comment on your application "Beamer"'
    assert msg.text.startswith("Hello,")


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
    # The internal check comes first, so the function builds no service at all.
    assert _FakeService.last is None


async def test_applicant_comment_mails_actionable_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_actionable(
        session: Any, *, application_id: Any, state: Any
    ) -> list[str]:
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
    # The preference filter reports the applicant address as opted out.
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


def _capture_context(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the render context of each builtin mail."""
    seen: list[dict[str, Any]] = []
    real = mod.render_mail

    def spy(**kwargs: Any) -> Any:
        seen.append(kwargs["context"])
        return real(**kwargs)

    monkeypatch.setattr(mod, "render_mail", spy)
    return seen


async def test_principal_comment_mail_names_the_gremium_not_the_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A12/O16: the applicant mail shows the Gremium, never the member name."""
    seen = _capture_context(monkeypatch)
    gremium_id = uuid.uuid4()
    # executes: the application row, then the (lang, gremium_id) row for the
    # language. scalar: the Gremium name. scalars: the preference filter.
    session = cast(
        AsyncSession,
        FakeSession(
            executes=[_app_row(gremium_id=gremium_id), [("de", gremium_id)]],
            scalar=["AStA Finanzen"],
            scalars=[[]],
        ),
    )
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="principal",
        visibility="public",
        body="Bitte Angebot nachreichen.",
        author_name="Max Mitglied",
    )
    assert sent == 1
    svc = _FakeService.last
    assert svc is not None
    msg = svc.enqueued[0]
    assert "von AStA Finanzen:" in msg.text
    assert "Max Mitglied" not in msg.text
    assert seen[0]["commentAuthor"] == "AStA Finanzen"
    assert seen[0]["commentAuthorInitials"] == "AF"


async def test_principal_comment_mail_without_gremium_uses_the_committee_label() -> None:
    """Without a Gremium the mail shows the generic label, not the member name."""
    session = cast(
        AsyncSession,
        FakeSession(executes=[_app_row(), [("en", None)]], scalars=[[]]),
    )
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="principal",
        visibility="public",
        body="Please add the quote.",
        author_name="Max Mitglied",
    )
    assert sent == 1
    svc = _FakeService.last
    assert svc is not None
    msg = svc.enqueued[0]
    assert "from Committee:" in msg.text
    assert "Max Mitglied" not in msg.text



async def test_applicant_comment_mail_keeps_the_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The team mail keeps the display name of the author."""

    async def fake_actionable(
        session: Any, *, application_id: Any, state: Any
    ) -> list[str]:
        return ["team@x.de"]

    monkeypatch.setattr(mod, "actionable_principal_emails", fake_actionable)
    seen = _capture_context(monkeypatch)
    session = cast(AsyncSession, FakeSession(executes=[_app_row()], scalars=[[]]))
    sent = await send_comment_notifications(
        session,
        queue=FakeQueue(),
        settings=SETTINGS,
        application_id=uuid.uuid4(),
        comment_id=uuid.uuid4(),
        author_kind="applicant",
        visibility="public",
        body="Wann?",
        author_name="Anna Antrag",
    )
    assert sent == 1
    assert seen[0]["commentAuthor"] == "Anna Antrag"
    assert seen[0]["commentAuthorInitials"] == "AA"
