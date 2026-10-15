"""Deep links of the mails: the URL builders, the layout and the service."""

from __future__ import annotations

import uuid

from app.modules.notifications.layout import append_link_text, render_layout
from app.modules.notifications.links import (
    MailLink,
    application_link,
    meeting_link,
    privacy_admin_link,
    protocol_link,
    public_protocol_url,
    task_link,
)
from app.modules.notifications.models import MailTemplate
from app.modules.notifications.service import NotificationService
from app.settings import load_settings
from tests._support.notifications_fakes import FakeQueue, FakeSession

SETTINGS = load_settings()
BASE = SETTINGS.public_base_url.rstrip("/")
ID = uuid.uuid4()


def test_url_builders_point_at_the_frontend_routes() -> None:
    assert application_link(SETTINGS, ID).url == f"{BASE}/applications/{ID}"
    assert application_link(SETTINGS, ID, guest=True).url == f"{BASE}/antrag/{ID}"
    assert task_link(SETTINGS, ID).url == f"{BASE}/tasks/{ID}"
    assert meeting_link(SETTINGS, ID).url == f"{BASE}/meetings/{ID}"
    assert protocol_link(SETTINGS, ID).url == f"{BASE}/meetings/{ID}"
    assert protocol_link(SETTINGS, ID).target == "protocol"
    assert public_protocol_url(SETTINGS, ID) == f"{BASE}/protokolle/{ID}"
    assert privacy_admin_link(SETTINGS).url == f"{BASE}/admin/privacy"


def test_label_follows_the_language_with_a_german_fallback() -> None:
    link = MailLink("https://x.de/a", "meeting")
    assert link.label("de") == "Sitzung öffnen"
    assert link.label("en") == "Open the meeting"
    assert link.label("fr") == "Sitzung öffnen"


def test_append_link_text_adds_one_line() -> None:
    out = append_link_text("Hallo,\n\nText.\n", "https://x.de/a", "Antrag öffnen")
    assert out == "Hallo,\n\nText.\n\nAntrag öffnen: https://x.de/a\n"


def test_append_link_text_keeps_a_text_that_has_the_url() -> None:
    text = "Hier: https://x.de/a\n"
    assert append_link_text(text, "https://x.de/a", "Antrag öffnen") == text


def _layout(content: str, url: str | None) -> str:
    return render_layout(
        content_html=content,
        title="T",
        site_name="S",
        base_url="https://x.de",
        reason="R",
        action_url=url,
        action_label="Antrag öffnen" if url else None,
    )


def test_layout_adds_the_button_escaped() -> None:
    out = _layout("<p>Text</p>", "https://x.de/a?b=1&c=2")
    assert 'href="https://x.de/a?b=1&amp;c=2"' in out
    assert ">Antrag öffnen</a>" in out


def test_layout_omits_the_button_when_the_content_links_the_url() -> None:
    content = '<p><a href="https://x.de/a">https://x.de/a</a></p>'
    assert ">Antrag öffnen</a>" not in _layout(content, "https://x.de/a")


def test_layout_without_a_link_has_no_button() -> None:
    assert "Antrag öffnen" not in _layout("<p>Text</p>", None)


async def test_send_kind_mail_adds_the_link_to_text_and_html() -> None:
    session = FakeSession(scalars=[[], []])  # no opt-out, no DB template
    queue = FakeQueue()
    svc = NotificationService(session, queue=queue, settings=SETTINGS)  # type: ignore[arg-type]
    link = meeting_link(SETTINGS, ID)
    ok = await svc.send_kind_mail(
        ["a@x.de"],
        kind="meeting",
        template_key="meeting_created",
        builtin_subject={"de": "Neue Sitzung"},
        builtin_body={"de": "Hallo,\n\neine Sitzung.\n"},
        context={},
        idempotency_parts=("meeting_created", str(ID)),
        link=link,
    )
    assert ok is True
    msg = queue.messages[0]
    assert msg.text.endswith(f"Sitzung öffnen: {link.url}\n")
    assert f'href="{link.url}"' in msg.html


async def test_send_kind_mail_gives_the_template_the_link_placeholder() -> None:
    """An override that places `{{ link }}` gets the URL once, not a second line."""
    tpl = MailTemplate(
        key="meeting_created",
        subject_i18n={"de": "Sitzung"},
        body_i18n={"de": "Zur Sitzung: {{ link }}"},
        body_html_i18n={},
        placeholders={},
    )
    session = FakeSession(scalars=[[], [tpl]])
    queue = FakeQueue()
    svc = NotificationService(session, queue=queue, settings=SETTINGS)  # type: ignore[arg-type]
    link = meeting_link(SETTINGS, ID)
    await svc.send_kind_mail(
        ["a@x.de"],
        kind="meeting",
        template_key="meeting_created",
        builtin_subject={"de": "x"},
        builtin_body={"de": "x"},
        context={},
        idempotency_parts=("meeting_created", str(ID)),
        link=link,
    )
    assert queue.messages[0].text == f"Zur Sitzung: {link.url}"


async def test_send_kind_mail_without_a_link_renders_an_empty_placeholder() -> None:
    """A template with `{{ link }}` stays safe under StrictUndefined without a link."""
    tpl = MailTemplate(
        key="erasure_executed",
        subject_i18n={"de": "Gelöscht"},
        body_i18n={"de": "Fertig.{{ link }}"},
        body_html_i18n={},
        placeholders={},
    )
    session = FakeSession(scalars=[[], [tpl]])
    queue = FakeQueue()
    svc = NotificationService(session, queue=queue, settings=SETTINGS)  # type: ignore[arg-type]
    await svc.send_kind_mail(
        ["a@x.de"],
        kind="privacy",
        template_key="erasure_executed",
        builtin_subject={"de": "x"},
        builtin_body={"de": "x"},
        context={},
        idempotency_parts=("erasure_executed", str(ID)),
    )
    assert queue.messages[0].text == "Fertig."
