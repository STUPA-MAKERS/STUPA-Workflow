"""Notification service tests (T-18): template CRUD, the notify action and magic link.

`FakeSession` answers the database queries and `FakeQueue` takes the send calls, so the
tests need no SMTP and no Redis.
"""

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
from tests._support.notifications_fakes import FakeQueue, FakeResolver, FakeSession

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


async def test_create_template_ok() -> None:
    session = FakeSession(scalars=[[]])  # _get_template_by_key finds no collision
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
    # The merge (#12) keeps the full builtin catalog plus the rows outside the catalog.
    ta, tb = _template("a"), _template("b")
    ta.id, tb.id = uuid.uuid4(), uuid.uuid4()
    session = FakeSession(scalars=[[ta, tb]])
    out = await _service(session).list_templates()
    by_key = {t.key: t for t in out}
    # Builtin defaults come without a database id and with source='builtin'.
    assert by_key["status_update"].source == "builtin"
    assert by_key["status_update"].id is None
    # The committee-facing notify default (bug #2) is editable via the merge too.
    assert by_key["status_update_team"].source == "builtin"
    # Existing overrides outside the catalog go to the end with source='override'.
    assert by_key["a"].source == "override" and by_key["b"].source == "override"
    assert out[-2].key == "a" and out[-1].key == "b"


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


async def test_handle_notify_action_inline_mode() -> None:
    # First scalars call: the preference filter (#4-2, no opt-out). Then the template.
    session = FakeSession(scalars=[[], [_template()]])
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


async def test_handle_notify_action_inline_missing_template_falls_back() -> None:
    # An unknown template falls back to a variable-free builtin, not to a silent drop.
    session = FakeSession(scalars=[[], []])
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
    assert await svc.handle_notify_action({"type": "notify", "templateKey": "x"}) == 1
    assert len(queue.messages) == 1


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


async def test_handle_notify_action_derives_real_kind_from_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AUD-043: the opt-out filter and the footer use the catalog kind.

    They do not use a substring heuristic. A `comment_team` template has the catalog
    kind `comment`, so the filter must treat it as `comment`. The old
    `'deadline' in key else 'status_update'` test always gave `status_update`, so a
    comment opt-out had no effect.
    """
    import app.modules.notifications.service as svc_mod

    captured: dict[str, str] = {}

    async def _spy(_session: object, recipients: list[str], kind: str) -> list[str]:
        captured["kind"] = kind
        return recipients

    monkeypatch.setattr(svc_mod, "filter_recipients_by_preference", _spy)

    session = FakeSession(scalars=[[_template("comment_team")]])
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "comment_team",
         "recipients": [{"kind": "applicant"}]},
        context={"status": "Y"},
    )
    assert count == 1
    # Opt-out filter keyed by the real kind, not the old `status_update`.
    assert captured["kind"] == "comment"
    # Footer reason text matches the comment kind, not status_update.
    assert "neuen Kommentar" in queue.messages[0].html


async def test_handle_notify_action_unknown_key_defaults_to_status_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-catalogue keys fall back to `status_update` (fail-open default)."""
    import app.modules.notifications.service as svc_mod

    captured: dict[str, str] = {}

    async def _spy(_session: object, recipients: list[str], kind: str) -> list[str]:
        captured["kind"] = kind
        return recipients

    monkeypatch.setattr(svc_mod, "filter_recipients_by_preference", _spy)

    session = FakeSession(scalars=[[]])  # no DB template → builtin fallback
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
    await svc.handle_notify_action(
        {"type": "notify", "templateKey": "custom_unlisted",
         "recipients": [{"kind": "applicant"}]},
    )
    assert captured["kind"] == "status_update"


async def test_notify_without_template_key_splits_applicant_and_team() -> None:
    """Bug #2: without a templateKey the send splits by recipient kind.

    The applicant gets `status_update`. Every other recipient kind gets the
    Gremium-facing `status_update_team` wording.
    """
    # Per send: scalars #1 = preference filter, #2 = template lookup (builtin).
    session = FakeSession(scalars=[[], [], [], []])
    queue = FakeQueue()
    svc = _service(session, queue)
    resolver = FakeResolver(["a@x.de"])
    svc.resolver = resolver  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "recipients": [
            {"kind": "gremium", "ref": "g1"},
            {"kind": "applicant"},
            {"kind": "email", "ref": "b@x.de"},
        ]},
        application_id=uuid.uuid4(),
        context={"applicationTitle": "T", "status": "Neu"},
        lang="de",
    )
    assert count == 2
    applicant_msg, team_msg = queue.messages
    assert applicant_msg.subject == "Aktualisierung zu Ihrem Antrag"
    assert team_msg.subject == "Statuswechsel: Antrag „T“"
    assert "Aktion oder Abstimmung" in team_msg.text
    # Template key is part of the idempotency parts → distinct keys.
    assert applicant_msg.idempotency_key != team_msg.idempotency_key
    # Partitioning: applicant spec resolved separately from the rest.
    assert resolver.calls[0][0] == [{"kind": "applicant"}]
    assert resolver.calls[1][0] == [
        {"kind": "gremium", "ref": "g1"},
        {"kind": "email", "ref": "b@x.de"},
    ]


async def test_notify_without_template_key_applicant_only_single_send() -> None:
    session = FakeSession(scalars=[[], []])
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "recipients": [{"kind": "applicant"}]},
        application_id=uuid.uuid4(),
        lang="de",
    )
    assert count == 1
    assert len(queue.messages) == 1
    assert queue.messages[0].subject == "Aktualisierung zu Ihrem Antrag"


async def test_notify_without_template_key_team_only_single_send() -> None:
    session = FakeSession(scalars=[[], []])
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver(["t@x.de"])  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "recipients": [{"kind": "role", "ref": "manager"}]},
        lang="de",
    )
    assert count == 1
    assert len(queue.messages) == 1
    assert queue.messages[0].subject == "Statuswechsel: Antrag"


async def test_notify_explicit_template_key_sends_once_for_all() -> None:
    """Regression: an explicit templateKey keeps the single combined send."""
    session = FakeSession(scalars=[[], [_template()]])
    queue = FakeQueue()
    svc = _service(session, queue)
    resolver = FakeResolver(["a@x.de", "t@x.de"])
    svc.resolver = resolver  # type: ignore[assignment]
    specs = [{"kind": "applicant"}, {"kind": "email", "ref": "t@x.de"}]
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "status_update", "recipients": specs},
        application_id=uuid.uuid4(),
        context={"status": "Y"},
    )
    assert count == 1
    assert len(queue.messages) == 1
    assert queue.messages[0].to == ("a@x.de", "t@x.de")
    assert len(resolver.calls) == 1 and resolver.calls[0][0] == specs


async def test_notify_split_sends_filter_preferences_as_status_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both default sends respect an opt-out of kind `status_update`.

    `status_update_team` maps to the same catalog kind.
    """
    import app.modules.notifications.service as svc_mod

    kinds: list[str] = []

    async def _spy(_session: object, recipients: list[str], kind: str) -> list[str]:
        kinds.append(kind)
        return recipients

    monkeypatch.setattr(svc_mod, "filter_recipients_by_preference", _spy)

    session = FakeSession(scalars=[[], []])  # template lookups only (filter spied)
    queue = FakeQueue()
    svc = _service(session, queue)
    svc.resolver = FakeResolver(["a@x.de"])  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "recipients": [
            {"kind": "applicant"},
            {"kind": "gremium", "ref": "g1"},
        ]},
    )
    assert count == 2
    assert kinds == ["status_update", "status_update"]


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
    session = FakeSession(scalars=[[]])  # no magic_link template
    queue = FakeQueue()
    await _service(session, queue).send_magic_link(email="a@x.de", link="https://l/#t=2")
    assert "https://l/#t=2" in queue.messages[0].text


async def test_enqueue_without_queue_drops(caplog: pytest.LogCaptureFixture) -> None:
    session = FakeSession(scalars=[[]])
    # With queue=None, send_magic_link logs and drops the mail without an error.
    await _service(session, None).send_magic_link(email="a@x.de", link="https://l")


async def test_idempotency_base_changes_key() -> None:
    app_id = uuid.uuid4()

    async def run(base: str | None) -> str:
        session = FakeSession(scalars=[[], [_template()]])
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
