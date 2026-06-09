"""Service-Tests Notifications (T-18): Template-CRUD, notify-Action, Magic-Link —
DB via `FakeSession`, Versand via `FakeQueue` (kein echtes SMTP/Redis)."""

from __future__ import annotations

import uuid

import pytest

from app.modules.notifications.models import MailTemplate
from app.modules.notifications.schemas import (
    MailPreviewRequest,
    MailTemplateCreate,
    MailTemplateUpdate,
)
from app.modules.notifications.service import NotificationService
from app.settings import load_settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests.notifications_fakes import FakeQueue, FakeResolver, FakeSession

SETTINGS = load_settings()


def _service(session: FakeSession, queue: FakeQueue | None = None) -> NotificationService:
    return NotificationService(session, queue=queue, settings=SETTINGS)  # type: ignore[arg-type]


def _template(key: str = "status_update") -> MailTemplate:
    return MailTemplate(
        key=key,
        subject_i18n={"de": "Status {{ status }}"},
        body_i18n={"de": "Neuer Status: {{ status }}"},
        body_html_i18n={},
        placeholders={},
    )


# --------------------------------------------------------------------------- templates
async def test_create_template_ok() -> None:
    session = FakeSession(scalars=[[]])  # _get_template_by_key → keine Kollision
    out = await _service(session).create_template(
        MailTemplateCreate(
            key="welcome",
            subjectI18n={"de": "Hi"},
            bodyI18n={"de": "Body"},
        )
    )
    assert out.key == "welcome"
    assert session.committed == 1


async def test_create_template_duplicate_conflict() -> None:
    existing = _template("welcome")
    session = FakeSession(scalars=[[existing]])
    with pytest.raises(ConflictError):
        await _service(session).create_template(
            MailTemplateCreate(key="welcome", subjectI18n={"de": "x"}, bodyI18n={"de": "y"})
        )


async def test_list_templates() -> None:
    ta, tb = _template("a"), _template("b")
    ta.id, tb.id = uuid.uuid4(), uuid.uuid4()
    session = FakeSession(scalars=[[ta, tb]])
    out = await _service(session).list_templates()
    assert [t.key for t in out] == ["a", "b"]


async def test_update_template_changes_fields() -> None:
    tpl = _template("welcome")
    session = FakeSession()
    session.add(tpl)
    out = await _service(session).update_template(
        tpl.id,
        MailTemplateUpdate(
            subjectI18n={"de": "neu"},
            bodyI18n={"de": "neu body"},
            bodyHtmlI18n={"de": "<b>x</b>"},
            placeholders={"x": "y"},
        ),
    )
    assert out.subject_i18n == {"de": "neu"}
    assert out.body_html_i18n == {"de": "<b>x</b>"}


async def test_update_template_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _service(FakeSession()).update_template(uuid.uuid4(), MailTemplateUpdate())


async def test_update_template_empty_payload_keeps_fields() -> None:
    tpl = _template("welcome")
    session = FakeSession()
    session.add(tpl)
    out = await _service(session).update_template(tpl.id, MailTemplateUpdate())
    assert out.key == "welcome" and out.subject_i18n == tpl.subject_i18n


async def test_preview_template_renders() -> None:
    tpl = _template()
    session = FakeSession()
    session.add(tpl)
    out = await _service(session).preview_template(
        tpl.id, MailPreviewRequest(lang="de", context={"status": "Bewilligt"})
    )
    assert out.subject == "Status Bewilligt"
    assert out.lang == "de"


async def test_preview_template_render_error_422() -> None:
    tpl = MailTemplate(
        key="bad", subject_i18n={"de": "{{ missing }}"}, body_i18n={"de": "b"},
        body_html_i18n={}, placeholders={},
    )
    session = FakeSession()
    session.add(tpl)
    with pytest.raises(ValidationProblem):
        await _service(session).preview_template(tpl.id, MailPreviewRequest(context={}))


async def test_preview_template_not_found() -> None:
    with pytest.raises(NotFoundError):
        await _service(FakeSession()).preview_template(uuid.uuid4(), MailPreviewRequest())


# --------------------------------------------------------------------------- notify action
async def test_handle_notify_action_inline_mode() -> None:
    session = FakeSession(scalars=[[_template()]])
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "status_update",
         "recipients": [{"kind": "applicant"}]},
        application_id=uuid.uuid4(),
        context={"status": "Y"},
    )
    assert count == 1
    assert queue.messages[0].subject == "Status Y"


async def test_handle_notify_action_inline_missing_template() -> None:
    session = FakeSession(scalars=[[]])
    svc = _service(session, FakeQueue())
    svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
    assert await svc.handle_notify_action({"type": "notify", "templateKey": "x"}) == 0


async def test_handle_notify_action_without_template() -> None:
    svc = _service(FakeSession(), FakeQueue())
    assert await svc.handle_notify_action({"type": "notify"}) == 0


async def test_handle_notify_action_no_recipients_skips() -> None:
    session = FakeSession(scalars=[[_template()]])
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver([])  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "status_update", "recipients": []},
        context={"status": "Y"},
    )
    assert count == 0
    assert queue.messages == []


# --------------------------------------------------------------------------- magic link
async def test_send_magic_link_uses_db_template() -> None:
    tpl = MailTemplate(
        key="magic_link", subject_i18n={"de": "Link"},
        body_i18n={"de": "Hier: {{ link }}"}, body_html_i18n={}, placeholders={},
    )
    session = FakeSession(scalars=[[tpl]])
    queue = FakeQueue()
    await _service(session, queue).send_magic_link(email="a@x.de", link="https://l/#t=1")
    assert queue.messages[0].to == ("a@x.de",)
    assert "https://l/#t=1" in queue.messages[0].text


async def test_send_magic_link_builtin_fallback() -> None:
    session = FakeSession(scalars=[[]])  # kein magic_link-Template
    queue = FakeQueue()
    await _service(session, queue).send_magic_link(email="a@x.de", link="https://l/#t=2")
    assert "https://l/#t=2" in queue.messages[0].text


async def test_enqueue_without_queue_drops(caplog: pytest.LogCaptureFixture) -> None:
    session = FakeSession(scalars=[[]])
    # queue=None → send_magic_link loggt + verwirft, kein Fehler.
    await _service(session, None).send_magic_link(email="a@x.de", link="https://l")


async def test_idempotency_base_changes_key() -> None:
    app_id = uuid.uuid4()

    async def run(base: str | None) -> str:
        session = FakeSession(scalars=[[_template()]])
        queue = FakeQueue()
        svc = _service(session, queue)
        svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
        await svc.handle_notify_action(
            {"type": "notify", "templateKey": "status_update",
             "recipients": [{"kind": "applicant"}]},
            application_id=app_id,
            context={"status": "Z"},
            idempotency_base=base,
        )
        return queue.messages[0].idempotency_key

    assert await run("base-A") != await run(None)
