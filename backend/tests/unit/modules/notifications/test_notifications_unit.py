"""Unit-Tests der reinen Notifications-Bausteine (T-18): events, mail, templating,
queue, schemas, provider — ohne DB/Redis."""

from __future__ import annotations

import pytest

from app.modules.notifications import events
from app.modules.notifications.mail import (
    CapturingMailSender,
    MailMessage,
    SmtpMailSender,
    build_email_message,
    compute_idempotency_key,
)
from app.modules.notifications.queue import ArqMailQueue, DirectMailQueue
from app.modules.notifications.schemas import MailTemplateOut
from app.modules.notifications.templating import TemplateRenderError, render_mail
from app.settings import load_settings

SETTINGS = load_settings(
    DATABASE_URL="postgresql+asyncpg://app:pw@localhost/x",
    SESSION_SECRET="x" * 16,
    MAGIC_LINK_SECRET="y" * 16,
)


# --------------------------------------------------------------------------- events
def test_event_list_and_membership() -> None:
    assert events.is_event("status_changed")
    assert not events.is_event("nope")
    assert "application_created" in events.EVENT_SET
    assert len(events.EVENTS) == len(events.EVENT_SET)


# --------------------------------------------------------------------------- mail
def test_idempotency_key_deterministic_and_distinct() -> None:
    a = compute_idempotency_key("status_changed", "app1", "rule1")
    b = compute_idempotency_key("status_changed", "app1", "rule1")
    c = compute_idempotency_key("status_changed", "app1", "rule2")
    assert a == b != c
    assert a.startswith("mail:")


def test_mail_message_payload_roundtrip_and_domains() -> None:
    msg = MailMessage(
        to=("a@x.de", "b@y.com"),
        subject="Hi",
        text="t",
        html="<p>t</p>",
        idempotency_key="mail:1",
        from_addr="f@z.de",
        from_name="F",
    )
    again = MailMessage.from_payload(msg.to_payload())
    assert again == msg
    assert msg.recipient_domains() == ["x.de", "y.com"]


def test_build_email_message_text_and_html() -> None:
    msg = MailMessage(to=("a@x.de",), subject="S", text="body", html="<b>body</b>")
    email = build_email_message(msg, SETTINGS)
    assert email["To"] == "a@x.de"
    assert email["Subject"] == "S"
    assert SETTINGS.mail_from in email["From"]
    assert email.is_multipart()  # Text + HTML-Alternative


def test_build_email_message_without_from_name() -> None:
    s = load_settings(mail_from_name="")
    email = build_email_message(MailMessage(to=("a@x.de",), subject="S", text="b"), s)
    assert email["From"] == s.mail_from


async def test_capturing_sender_collects() -> None:
    sender = CapturingMailSender()
    msg = MailMessage(to=("a@x.de",), subject="S", text="b", idempotency_key="k")
    await sender.send(msg)
    assert sender.sent == [msg]


async def test_smtp_sender_no_recipients_is_noop() -> None:
    sender = SmtpMailSender(SETTINGS)
    await sender.send(MailMessage(to=(), subject="S", text="b"))  # kein Netzwerk


async def test_smtp_sender_sends_via_aiosmtplib(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_send(email: object, **kw: object) -> None:
        captured["email"] = email
        captured["kw"] = kw

    import aiosmtplib

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    s = load_settings(smtp_host="mail.local")
    await SmtpMailSender(s).send(MailMessage(to=("a@x.de",), subject="S", text="b"))
    assert captured["kw"]["hostname"] == "mail.local"  # type: ignore[index]


# --------------------------------------------------------------------------- templating
def test_render_mail_uses_requested_lang_and_html() -> None:
    out = render_mail(
        subject_i18n={"de": "Hallo {{ name }}", "en": "Hi {{ name }}"},
        body_i18n={"de": "Text {{ name }}", "en": "Text en"},
        body_html_i18n={"en": "<b>{{ name }}</b>"},
        context={"name": "Max"},
        lang="en",
    )
    assert out.subject == "Hi Max"
    assert out.html == "<b>Max</b>"
    assert out.lang == "en"


def test_render_mail_fallback_to_default_lang() -> None:
    out = render_mail(
        subject_i18n={"de": "Betreff"},
        body_i18n={"de": "Body"},
        context={},
        lang="fr",
        default_lang="de",
    )
    assert out.subject == "Betreff"
    assert out.lang == "de"


def test_render_mail_fallback_to_any_when_default_missing() -> None:
    out = render_mail(
        subject_i18n={"it": "Oggetto"},
        body_i18n={"it": "Corpo"},
        context={},
        lang="fr",
        default_lang="de",
    )
    assert out.subject == "Oggetto"
    assert out.lang == "it"


def test_render_mail_missing_body_raises() -> None:
    with pytest.raises(TemplateRenderError):
        render_mail(subject_i18n={"de": "x"}, body_i18n={}, context={})


def test_render_mail_unknown_placeholder_raises() -> None:
    with pytest.raises(TemplateRenderError):
        render_mail(
            subject_i18n={"de": "{{ missing }}"},
            body_i18n={"de": "b"},
            context={},
        )


def test_render_mail_subject_strips_crlf_header_injection() -> None:
    out = render_mail(
        subject_i18n={"de": "Betreff {{ x }}"},
        body_i18n={"de": "b"},
        context={"x": "ok\r\nBcc: evil@x.de"},
    )
    assert "\n" not in out.subject and "\r" not in out.subject
    assert "Bcc:" in out.subject  # Inhalt bleibt, nur Umbruch entfernt


def test_render_html_autoescape() -> None:
    out = render_mail(
        subject_i18n={"de": "s"},
        body_i18n={"de": "b"},
        body_html_i18n={"de": "{{ v }}"},
        context={"v": "<x>"},
    )
    assert out.html == "&lt;x&gt;"  # autoescape im HTML-Body


# --------------------------------------------------------------------------- queue
async def test_arq_queue_enqueues_with_idempotent_job_id() -> None:
    calls: list[tuple[str, dict, str | None]] = []

    class FakePool:
        async def enqueue_job(self, name, payload, *, _job_id=None):  # noqa: ANN001
            calls.append((name, payload, _job_id))
            return object()

    q = ArqMailQueue(FakePool())
    await q.enqueue(MailMessage(to=("a@x.de",), subject="s", text="b", idempotency_key="k1"))
    assert calls[0][0] == "send_mail"
    assert calls[0][2] == "k1"


async def test_arq_queue_dedup_logs_when_none(caplog: pytest.LogCaptureFixture) -> None:
    class FakePool:
        async def enqueue_job(self, *a, **k):  # noqa: ANN002, ANN003
            return None  # arq: Job-Id existiert bereits

    q = ArqMailQueue(FakePool())
    await q.enqueue(MailMessage(to=("a@x.de",), subject="s", text="b", idempotency_key="dup"))
    # kein Fehler; Dedup-Pfad genommen.


async def test_direct_queue_sends_once_per_key() -> None:
    sender = CapturingMailSender()
    q = DirectMailQueue(sender)
    msg = MailMessage(to=("a@x.de",), subject="s", text="b", idempotency_key="k")
    await q.enqueue(msg)
    await q.enqueue(msg)  # gleicher Key → dedupliziert
    assert len(sender.sent) == 1


async def test_direct_queue_without_key_always_sends() -> None:
    sender = CapturingMailSender()
    q = DirectMailQueue(sender)
    msg = MailMessage(to=("a@x.de",), subject="s", text="b")
    await q.enqueue(msg)
    await q.enqueue(msg)
    assert len(sender.sent) == 2


# --------------------------------------------------------------------------- schemas
def test_template_out_serializes_camel() -> None:
    from uuid import uuid4

    out = MailTemplateOut(
        id=uuid4(),
        key="k",
        subject_i18n={"de": "s"},
        body_i18n={"de": "b"},
        body_html_i18n={},
        placeholders={},
    )
    dumped = out.model_dump(by_alias=True)
    assert "subjectI18n" in dumped and "bodyHtmlI18n" in dumped


# --------------------------------------------------------------------------- provider
async def test_create_mail_pool_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import arq

    async def boom(*a, **k):  # noqa: ANN002, ANN003
        raise OSError("no redis")

    monkeypatch.setattr(arq, "create_pool", boom)
    from app.modules.notifications.provider import create_mail_pool

    assert await create_mail_pool("redis://localhost:6379/0") is None


async def test_create_mail_pool_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import arq

    sentinel = object()

    async def ok(*a, **k):  # noqa: ANN002, ANN003
        return sentinel

    monkeypatch.setattr(arq, "create_pool", ok)
    from app.modules.notifications.provider import (
        create_mail_pool,
        mail_queue_from_pool,
    )

    pool = await create_mail_pool("redis://localhost:6379/0")
    assert pool is sentinel
    assert mail_queue_from_pool(pool) is not None
    assert mail_queue_from_pool(None) is None


async def test_close_mail_pool_handles_none_and_object() -> None:
    from app.modules.notifications.provider import close_mail_pool

    await close_mail_pool(None)

    closed: list[bool] = []

    class FakePool:
        async def aclose(self) -> None:
            closed.append(True)

    await close_mail_pool(FakePool())  # type: ignore[arg-type]
    assert closed == [True]
