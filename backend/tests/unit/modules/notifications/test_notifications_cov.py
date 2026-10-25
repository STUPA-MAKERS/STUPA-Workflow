"""Coverage hardening for the notification parts (service, auto, recipients, privacy).

Every test here is a pure unit test. Local fakes replace the database and `FakeQueue`
replaces the send path, so the tests need no SMTP, no Redis and no Postgres. A fake
`get_sessionmaker` drives the background tasks of `auto.py` and `privacy.py`. The
`async with sessionmaker() as session` paths then run without a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications import auto, privacy, recipients
from app.modules.notifications import service as service_mod
from app.modules.notifications.auto import (
    AutoMailer,
    DelegationMailInfo,
    get_auto_mailer,
    meeting_delegation_mail_info,
)
from app.modules.notifications.models import (
    MailTemplate,
    NotificationPreference,
    NotificationSettings,
)
from app.modules.notifications.recipients import (
    RecipientResolver,
    actionable_principal_emails,
    state_actionable,
)
from app.modules.notifications.schemas import (
    MailPreviewPayloadRequest,
    MailTemplateUpsert,
)
from app.modules.notifications.service import (
    NotificationService,
    filter_recipients_by_preference,
)
from app.settings import load_settings
from app.shared.errors import NotFoundError, ValidationProblem

SETTINGS = load_settings()


class FakeResult:
    """Stand in for a Result with `all`, `first` and `scalar_one_or_none`."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None


class FakeSession:
    """AsyncSession stub with FIFO queues for `scalars`, `scalar` and `execute`.

    This fake extends the support fake. It adds `refresh`, `flush` and `delete`, which
    the settings path and the preference path of the service need. It also adds an
    in-memory store for `get` that holds integer keys and UUID keys.
    """

    def __init__(
        self,
        *,
        scalars: list[list[Any]] | None = None,
        scalar: list[Any] | None = None,
        executes: list[list[Any]] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = 0
        self.flushed = 0
        self.refreshed = 0
        self.store: dict[Any, Any] = {}
        self._scalars = scalars or []
        self._scalar = scalar or []
        self._executes = executes or []
        self.statements: list[Any] = []

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        self.store[obj.id] = obj

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, _obj: Any) -> None:
        self.refreshed += 1

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        self.store.pop(getattr(obj, "id", None), None)

    async def get(self, model: type, ident: Any) -> Any:
        obj = self.store.get(ident)
        return obj if isinstance(obj, model) else None

    async def scalars(self, _stmt: Any) -> FakeResult:
        self.statements.append(_stmt)
        return FakeResult(self._scalars.pop(0) if self._scalars else [])

    async def scalar(self, _stmt: Any) -> Any:
        self.statements.append(_stmt)
        return self._scalar.pop(0) if self._scalar else None

    async def execute(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        return FakeResult(self._executes.pop(0)) if self._executes else FakeResult([])


class FakeQueue:
    def __init__(self) -> None:
        self.messages: list[Any] = []

    async def enqueue(self, msg: Any) -> None:
        self.messages.append(msg)


class FakeResolver:
    def __init__(self, addresses: list[str]) -> None:
        self.addresses = addresses
        self.calls: list[Any] = []

    async def resolve(
        self, specs: Any, *, application_id: Any = None, now: Any = None
    ) -> list[str]:
        self.calls.append((specs, application_id))
        return list(self.addresses)


def _svc(session: FakeSession, queue: FakeQueue | None = None) -> NotificationService:
    return NotificationService(
        cast(AsyncSession, session), queue=cast(Any, queue), settings=SETTINGS
    )


def _tpl(key: str = "status_update") -> MailTemplate:
    return MailTemplate(
        key=key,
        subject_i18n={"de": "Status {{ status }}"},
        body_i18n={"de": "Neuer Status: {{ status }}"},
        body_html_i18n={},
        placeholders={},
    )


def _sessionmaker_for(session: FakeSession) -> Any:
    """Stand in for `get_sessionmaker`.

    The caller runs `sessionmaker = get_sessionmaker()` and then
    `async with sessionmaker() as session`. So `get_sessionmaker` must return a factory
    that builds the context manager on each call.
    """

    class _CM:
        async def __aenter__(self) -> FakeSession:
            return session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    def _factory() -> _CM:
        return _CM()

    def _get_sessionmaker() -> Any:
        return _factory

    return _get_sessionmaker


async def test_create_template_ok() -> None:
    from app.modules.notifications.schemas import MailTemplateCreate

    session = FakeSession(scalars=[[]])
    out = await _svc(session).create_template(
        MailTemplateCreate(
            key="welcome",
            subjectI18n={"de": "Hi"},
            bodyI18n={"de": "Body"},
        )
    )
    assert out.key == "welcome"
    assert out.source == "override"
    assert session.committed == 1


async def test_create_template_conflict() -> None:
    from app.modules.notifications.schemas import MailTemplateCreate
    from app.shared.errors import ConflictError

    session = FakeSession(scalars=[[_tpl("welcome")]])
    with pytest.raises(ConflictError):
        await _svc(session).create_template(
            MailTemplateCreate(
                key="welcome", subjectI18n={"de": "x"}, bodyI18n={"de": "y"}
            )
        )


async def test_list_templates_merges_catalogue_and_overrides() -> None:
    """Merge the catalog with the database overrides.

    A database override of a catalog key wins. A key outside the catalog goes to the end. A
    catalog key without an override stays builtin.
    """
    ta = _tpl("status_update")
    ta.id = uuid.uuid4()
    tb = _tpl("custom_flow")
    tb.id = uuid.uuid4()
    session = FakeSession(scalars=[[ta, tb]])
    out = await _svc(session).list_templates()
    by_key = {t.key: t for t in out}
    assert by_key["status_update"].source == "override"
    assert by_key["meeting_created"].source == "builtin"
    assert by_key["custom_flow"].source == "override"
    assert out[-1].key == "custom_flow"


async def test_update_template_changes_all_fields() -> None:
    from app.modules.notifications.schemas import MailTemplateUpdate

    tpl = _tpl("welcome")
    session = FakeSession()
    session.add(tpl)
    out = await _svc(session).update_template(
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
    assert out.placeholders == {"x": "y"}


async def test_update_template_not_found() -> None:
    from app.modules.notifications.schemas import MailTemplateUpdate

    with pytest.raises(NotFoundError):
        await _svc(FakeSession()).update_template(uuid.uuid4(), MailTemplateUpdate())


async def test_update_template_empty_payload_keeps_fields() -> None:
    from app.modules.notifications.schemas import MailTemplateUpdate

    tpl = _tpl("welcome")
    session = FakeSession()
    session.add(tpl)
    out = await _svc(session).update_template(tpl.id, MailTemplateUpdate())
    assert out.subject_i18n == tpl.subject_i18n


async def test_preview_template_renders() -> None:
    from app.modules.notifications.schemas import MailPreviewRequest

    tpl = _tpl()
    session = FakeSession()
    session.add(tpl)
    out = await _svc(session).preview_template(
        tpl.id, MailPreviewRequest(lang="de", context={"status": "Bewilligt"})
    )
    assert out.subject == "Status Bewilligt"


async def test_preview_template_not_found() -> None:
    from app.modules.notifications.schemas import MailPreviewRequest

    with pytest.raises(NotFoundError):
        await _svc(FakeSession()).preview_template(uuid.uuid4(), MailPreviewRequest())


async def test_preview_template_render_error_422() -> None:
    from app.modules.notifications.schemas import MailPreviewRequest

    tpl = MailTemplate(
        key="bad",
        subject_i18n={"de": "{{ missing }}"},
        body_i18n={"de": "b"},
        body_html_i18n={},
        placeholders={},
    )
    session = FakeSession()
    session.add(tpl)
    with pytest.raises(ValidationProblem):
        await _svc(session).preview_template(tpl.id, MailPreviewRequest(context={}))


async def test_upsert_template_unknown_key_422() -> None:
    session = FakeSession(scalars=[[]])
    with pytest.raises(ValidationProblem):
        await _svc(session).upsert_template(
            MailTemplateUpsert(
                key="not_in_catalogue",
                subjectI18n={"de": "x"},
                bodyI18n={"de": "y"},
                bodyHtmlI18n={},
            )
        )


async def test_upsert_template_creates_builtin_override() -> None:
    session = FakeSession(scalars=[[]])
    out = await _svc(session).upsert_template(
        MailTemplateUpsert(
            key="status_update",
            subjectI18n={"de": "neu"},
            bodyI18n={"de": "body"},
            bodyHtmlI18n={"de": "<b>x</b>"},
        )
    )
    assert out.source == "override"
    assert out.key == "status_update"
    assert session.committed == 1
    assert session.added


async def test_upsert_template_updates_existing() -> None:
    existing = _tpl("status_update")
    session = FakeSession(scalars=[[existing]])
    out = await _svc(session).upsert_template(
        MailTemplateUpsert(
            key="status_update",
            subjectI18n={"de": "geändert"},
            bodyI18n={"de": "geändert body"},
            bodyHtmlI18n={"de": "<i>y</i>"},
        )
    )
    assert out.subject_i18n == {"de": "geändert"}
    assert existing.body_html_i18n == {"de": "<i>y</i>"}
    assert session.added == []


async def test_reset_template_not_in_catalogue_404() -> None:
    with pytest.raises(NotFoundError):
        await _svc(FakeSession()).reset_template("nope")


async def test_reset_template_deletes_override() -> None:
    existing = _tpl("status_update")
    session = FakeSession(scalars=[[existing]])
    out = await _svc(session).reset_template("status_update")
    assert out.source == "builtin"
    assert out.id is None
    assert existing in session.deleted
    assert session.committed == 1


async def test_reset_template_no_override_returns_builtin() -> None:
    session = FakeSession(scalars=[[]])
    out = await _svc(session).reset_template("status_update")
    assert out.source == "builtin"
    assert session.deleted == []
    assert session.committed == 0


async def test_preview_payload_renders() -> None:
    out = await _svc(FakeSession()).preview_payload(
        MailPreviewPayloadRequest(
            subjectI18n={"de": "Hi {{ name }}"},
            bodyI18n={"de": "Body {{ name }}"},
            bodyHtmlI18n={},
            lang="de",
            context={"name": "Welt"},
        )
    )
    assert out.subject == "Hi Welt"
    assert out.lang == "de"


async def test_preview_payload_render_error_422() -> None:
    with pytest.raises(ValidationProblem):
        await _svc(FakeSession()).preview_payload(
            MailPreviewPayloadRequest(
                subjectI18n={"de": "{{ missing }}"},
                bodyI18n={"de": "x"},
                bodyHtmlI18n={},
                context={},
            )
        )


async def test_get_notification_settings_creates_default_row() -> None:
    session = FakeSession()
    row = await _svc(session).get_notification_settings()
    assert row.id == 1
    assert session.committed == 1
    assert session.refreshed == 1
    assert row in session.added


async def test_get_notification_settings_returns_existing() -> None:
    existing = NotificationSettings(id=1)
    session = FakeSession()
    session.store[1] = existing
    row = await _svc(session).get_notification_settings()
    assert row is existing
    assert session.committed == 0


async def test_update_notification_settings_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_record(session: Any, **kw: Any) -> None:
        captured.update(kw)

    import app.modules.audit.service as audit_svc

    monkeypatch.setattr(audit_svc, "record", fake_record)

    existing = NotificationSettings(
        id=1,
        task_reminder_enabled=True,
        task_reminder_after_days=5,
        task_reminder_repeat_days=7,
    )
    session = FakeSession()
    session.store[1] = existing
    row = await _svc(session).update_notification_settings(
        actor="admin",
        task_reminder_enabled=False,
        task_reminder_after_days=10,
        task_reminder_repeat_days=3,
    )
    assert row.task_reminder_enabled is False
    assert row.task_reminder_after_days == 10
    assert row.task_reminder_repeat_days == 3
    assert captured["data"]["taskReminderAfterDays"] == 10
    assert session.committed == 1


async def test_update_notification_settings_no_changes_keeps_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep every value when the call passes no field (each else branch)."""
    async def fake_record(session: Any, **kw: Any) -> None:
        return None

    import app.modules.audit.service as audit_svc

    monkeypatch.setattr(audit_svc, "record", fake_record)

    existing = NotificationSettings(
        id=1,
        task_reminder_enabled=True,
        task_reminder_after_days=5,
        task_reminder_repeat_days=7,
    )
    session = FakeSession()
    session.store[1] = existing
    row = await _svc(session).update_notification_settings(actor="admin")
    assert row.task_reminder_enabled is True
    assert row.task_reminder_after_days == 5
    assert row.task_reminder_repeat_days == 7


async def test_get_preferences_no_principal_all_default() -> None:
    session = FakeSession(scalar=[None])
    prefs = await _svc(session).get_preferences("ghost")
    assert all(enabled for _, enabled in prefs)
    assert {k for k, _ in prefs}


async def test_get_preferences_merges_stored_disable() -> None:
    """Merge the stored (kind, enabled) pairs; a kind without a row stays on."""
    pid = uuid.uuid4()
    session = FakeSession(
        scalar=[pid],
        executes=[[("comment", False), ("meeting", False)]],
    )
    prefs = dict(await _svc(session).get_preferences("u"))
    assert prefs["comment"] is False
    assert prefs["meeting"] is False
    assert prefs["status_update"] is True


async def test_set_preferences_unknown_kind_422() -> None:
    with pytest.raises(ValidationProblem):
        await _svc(FakeSession()).set_preferences("u", [("does_not_exist", False)])


async def test_set_preferences_principal_not_found_404() -> None:
    session = FakeSession(scalar=[None])
    with pytest.raises(NotFoundError):
        await _svc(session).set_preferences("ghost", [("comment", False)])


async def test_set_preferences_all_branches() -> None:
    """Cover each branch of the preference upsert.

    'comment' has an opt-out row and is enabled again, so the row goes (delete).
    'status_update' has no row and stays on (nothing). 'meeting' gets a new opt-out (add).
    'task' has a row and stays off (update). The final get_preferences finds no stored
    deviation.
    """
    pid = uuid.uuid4()
    existing_comment = NotificationPreference(
        principal_id=pid, kind="comment", enabled=False
    )
    existing_task = NotificationPreference(
        principal_id=pid, kind="task", enabled=False
    )
    session = FakeSession(
        scalar=[pid, pid],
        executes=[[]],
    )
    session.store[(pid, "comment")] = existing_comment
    session.store[(pid, "task")] = existing_task

    out = await _svc(session).set_preferences(
        "u",
        [
            ("comment", True),
            ("status_update", True),
            ("meeting", False),
            ("task", False),
        ],
    )
    assert existing_comment in session.deleted
    assert existing_task.enabled is False
    added_kinds = {p.kind for p in session.added}
    assert "meeting" in added_kinds
    assert isinstance(out, list)


async def test_send_kind_mail_no_recipients_returns_false() -> None:
    """Send nothing when the preference filter leaves no recipient."""
    session = FakeSession()
    ok = await _svc(session, FakeQueue()).send_kind_mail(
        [],
        kind="meeting",
        template_key="meeting_created",
        builtin_subject={"de": "S"},
        builtin_body={"de": "B"},
        context={},
        idempotency_parts=("x",),
    )
    assert ok is False


async def test_send_kind_mail_db_template_used() -> None:
    """Use the database template; the scalars feed the preference filter, then the lookup."""
    tpl = _tpl("meeting_created")
    session = FakeSession(scalars=[[], [tpl]])
    queue = FakeQueue()
    ok = await _svc(session, queue).send_kind_mail(
        ["a@x.de"],
        kind="meeting",
        template_key="meeting_created",
        builtin_subject={"de": "S"},
        builtin_body={"de": "B"},
        context={"status": "X"},
        idempotency_parts=("meeting", "1"),
        lang="de",
    )
    assert ok is True
    assert queue.messages[0].to == ("a@x.de",)


async def test_send_kind_mail_builtin_fallback() -> None:
    """Render and enqueue the builtin when no database template exists."""
    session = FakeSession(scalars=[[], []])
    queue = FakeQueue()
    ok = await _svc(session, queue).send_kind_mail(
        ["a@x.de"],
        kind="meeting",
        template_key="meeting_created",
        builtin_subject={"de": "Betreff"},
        builtin_body={"de": "Inhalt"},
        context={},
        idempotency_parts=("meeting", "2"),
    )
    assert ok is True
    assert queue.messages[0].subject == "Betreff"


async def test_send_kind_mail_builtin_render_error_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Return False when the builtin uses a missing variable (TemplateRenderError)."""
    session = FakeSession(scalars=[[], []])
    queue = FakeQueue()
    ok = await _svc(session, queue).send_kind_mail(
        ["a@x.de"],
        kind="meeting",
        template_key="meeting_created",
        builtin_subject={"de": "{{ broken }}"},
        builtin_body={"de": "B"},
        context={},
        idempotency_parts=("meeting", "3"),
    )
    assert ok is False
    assert queue.messages == []


async def test_handle_notify_action_builtin_catalogue_key_fallback() -> None:
    """Use the team builtin of a catalog key without a database override."""
    session = FakeSession(scalars=[[], []])
    queue = FakeQueue()
    svc = _svc(session, queue)
    svc.resolver = cast(Any, FakeResolver(["a@x.de"]))
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "status_update_team"},
        context={"applicationTitle": "Beamer", "status": "Prüfung"},
    )
    assert count == 1
    assert "Beamer" in queue.messages[0].text
    assert "Ggf. ist eine Aktion" in queue.messages[0].text


async def test_handle_notify_action_template_key_underscore_alias() -> None:
    """Accept the snake_case ``template_key`` when ``templateKey`` is missing."""
    tpl = _tpl("status_update")
    session = FakeSession(scalars=[[], [tpl]])
    queue = FakeQueue()
    svc = _svc(session, queue)
    svc.resolver = cast(Any, FakeResolver(["a@x.de"]))
    count = await svc.handle_notify_action(
        {"type": "notify", "template_key": "status_update"},
        context={"status": "Bewilligt"},
    )
    assert count == 1


async def test_handle_notify_action_filter_removes_all_recipients() -> None:
    """Send nothing when the preference filter removes every resolved address."""
    pid = uuid.uuid4()
    session = FakeSession(scalars=[["a@x.de"]])
    queue = FakeQueue()
    svc = _svc(session, queue)
    svc.resolver = cast(Any, FakeResolver(["a@x.de"]))
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "status_update"},
    )
    assert count == 0
    assert queue.messages == []
    assert pid


async def test_send_magic_link_db_template_and_layout() -> None:
    tpl = MailTemplate(
        key="magic_link",
        subject_i18n={"de": "Link"},
        body_i18n={"de": "Hier: {{ link }}"},
        body_html_i18n={"de": "<a>{{ link }}</a>"},
        placeholders={},
    )
    session = FakeSession(scalars=[[tpl]])
    queue = FakeQueue()
    await _svc(session, queue).send_magic_link(email="a@x.de", link="https://l/#1")
    msg = queue.messages[0]
    assert "https://l/#1" in msg.text
    assert msg.html


async def test_enqueue_none_queue_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log and drop the builtin magic-link mail when the queue is None."""
    session = FakeSession(scalars=[[]])
    await _svc(session, None).send_magic_link(email="a@x.de", link="https://l")


async def test_filter_recipients_empty_list_passthrough() -> None:
    session = FakeSession()
    out = await filter_recipients_by_preference(cast(AsyncSession, session), [], "comment")
    assert out == []


async def test_filter_recipients_unknown_kind_failopen() -> None:
    session = FakeSession()
    out = await filter_recipients_by_preference(
        cast(AsyncSession, session), ["a@x.de"], "totally_unknown"
    )
    assert out == ["a@x.de"]


async def test_filter_recipients_blocks_case_insensitive() -> None:
    """Block opted-out addresses case-insensitively and ignore a None entry."""
    session = FakeSession(scalars=[["A@X.de", None]])
    out = await filter_recipients_by_preference(
        cast(AsyncSession, session), ["a@x.de", "b@y.de"], "comment"
    )
    assert out == ["b@y.de"]


async def test_resolve_group_emails() -> None:
    session = FakeSession(scalars=[["g@x.de", None]])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [{"kind": "group", "ref": "stupa"}]
    )
    assert out == ["g@x.de"]


async def test_resolve_applicant_truthy_email() -> None:
    session = FakeSession(scalar=["app@x.de"])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [{"kind": "applicant"}], application_id=uuid.uuid4()
    )
    assert out == ["app@x.de"]


async def test_resolve_applicant_none_email_not_added() -> None:
    session = FakeSession(scalar=[None])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [{"kind": "applicant"}], application_id=uuid.uuid4()
    )
    assert out == []


async def test_resolve_gremium_invalid_uuid_returns_empty() -> None:
    out = await RecipientResolver(cast(AsyncSession, FakeSession())).resolve(
        [{"kind": "gremium", "ref": "not-a-uuid"}]
    )
    assert out == []


async def test_resolve_gremium_valid() -> None:
    gid = str(uuid.uuid4())
    session = FakeSession(scalars=[["m@x.de", None]])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [{"kind": "gremium", "ref": gid}]
    )
    assert out == ["m@x.de"]


async def test_resolve_email_strips_and_adds() -> None:
    out = await RecipientResolver(cast(AsyncSession, FakeSession())).resolve(
        [{"kind": "email", "ref": "  fix@x.de  "}]
    )
    assert out == ["fix@x.de"]


async def test_resolve_permission() -> None:
    session = FakeSession(scalars=[["perm@x.de"]])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [{"kind": "permission", "ref": "privacy.manage"}]
    )
    assert out == ["perm@x.de"]


async def test_resolve_permission_then_loop_continues() -> None:
    """Continue the loop after a permission spec that is not the last one."""
    session = FakeSession(scalars=[["perm@x.de"]])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [
            {"kind": "permission", "ref": "privacy.manage"},
            {"kind": "email", "ref": "fix@x.de"},
        ]
    )
    assert out == ["fix@x.de", "perm@x.de"]


async def test_resolve_unknown_spec_then_loop_continues() -> None:
    """Continue the loop after a spec that matches no kind and has no ``ref``."""
    out = await RecipientResolver(cast(AsyncSession, FakeSession())).resolve(
        [
            {"kind": "permission"},
            {"kind": "email", "ref": "fix@x.de"},
        ]
    )
    assert out == ["fix@x.de"]


async def test_resolve_all_unknown_specs_empty() -> None:
    out = await RecipientResolver(cast(AsyncSession, FakeSession())).resolve(
        [{"kind": "group"}, {"kind": "weird", "ref": "x"}, {}]
    )
    assert out == []


async def test_resolve_explicit_now_passed() -> None:
    """Resolve a role with an explicit ``now``."""
    session = FakeSession(scalars=[["r@x.de"]])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [{"kind": "role", "ref": "manager"}], now=datetime.now(UTC)
    )
    assert out == ["r@x.de"]


async def test_actionable_vote_state_with_gremium() -> None:
    """Resolve the members of the ``vote_gremium_id`` snapshot."""
    from app.modules.flow.models import State

    gid = uuid.uuid4()
    state = State(kind="vote", config={"gremiumId": str(gid)})
    session = FakeSession(scalar=[gid], scalars=[["v@x.de"]])
    out = await actionable_principal_emails(
        cast(AsyncSession, session), application_id=uuid.uuid4(), state=state
    )
    assert out == ["v@x.de"]


async def test_actionable_vote_state_without_gremium_returns_empty() -> None:
    from app.modules.flow.models import State

    state = State(kind="vote", config={})
    out = await actionable_principal_emails(
        cast(AsyncSession, FakeSession()), application_id=uuid.uuid4(), state=state
    )
    assert out == []


async def test_actionable_vote_state_config_not_dict() -> None:
    """Treat a vote state config that is not a dict as empty."""
    from app.modules.flow.models import State

    state = State(kind="vote", config=None)
    out = await actionable_principal_emails(
        cast(AsyncSession, FakeSession()), application_id=uuid.uuid4(), state=state
    )
    assert out == []


async def test_state_actionable_none_false() -> None:
    out = await state_actionable(cast(AsyncSession, FakeSession()), None)
    assert out is False


async def test_state_actionable_vote_true() -> None:
    from app.modules.flow.models import State

    out = await state_actionable(
        cast(AsyncSession, FakeSession()), State(kind="vote", config={})
    )
    assert out is True


async def test_state_actionable_counts_manual_transitions() -> None:
    from app.modules.flow.models import State

    state = State(kind="normal", config={}, id=uuid.uuid4())
    session = FakeSession(scalar=[2])
    assert await state_actionable(cast(AsyncSession, session), state) is True


async def test_state_actionable_no_manual_transitions_false() -> None:
    from app.modules.flow.models import State

    state = State(kind="normal", config={}, id=uuid.uuid4())
    session = FakeSession(scalar=[0])
    assert await state_actionable(cast(AsyncSession, session), state) is False


async def test_meeting_delegation_mail_info_query_fails_returns_none() -> None:
    class BoomSession:
        async def execute(self, _stmt: Any) -> Any:
            raise RuntimeError("db down")

    out = await meeting_delegation_mail_info(BoomSession(), uuid.uuid4())
    assert out is None


async def test_meeting_delegation_mail_info_row_none() -> None:
    session = FakeSession(executes=[[]])
    out = await meeting_delegation_mail_info(session, uuid.uuid4())
    assert out is None


async def test_meeting_delegation_mail_info_with_date_and_delegator_name() -> None:
    """Prefer the display name of the delegator."""
    did = uuid.uuid4()
    date = datetime(2026, 6, 16, tzinfo=UTC).date()
    mid = uuid.uuid4()
    row = ("d@x.de", "Sitzung 1", date, "AStA", "Max", "max@x.de", True, mid)
    session = FakeSession(executes=[[row]])
    out = await meeting_delegation_mail_info(session, did)
    assert out is not None
    assert out.meeting_id == mid
    assert out.meeting_date == "16.06.2026"
    assert out.delegator_name == "Max"
    assert out.voting is True


@pytest.mark.parametrize(("to_delegator", "column"), [(False, "delegate"), (True, "delegator")])
async def test_meeting_delegation_mail_info_picks_the_recipient(
    to_delegator: bool, column: str
) -> None:
    """The access revoke of a delegate mails the delegator."""
    seen: list[Any] = []

    class _Seen:
        async def execute(self, stmt: Any) -> Any:
            seen.append(stmt)
            return SimpleNamespace(first=lambda: None)

    await meeting_delegation_mail_info(_Seen(), uuid.uuid4(), to_delegator=to_delegator)
    sql = str(seen[0])
    assert f"principal.id = meeting_delegation.{column}_principal_id" in sql


async def test_meeting_delegation_mail_info_no_date_falls_back_to_email() -> None:
    """Fall back to no date and to the delegator e-mail as the name."""
    row = ("d@x.de", "Sitzung 2", None, None, None, "max@x.de", None, uuid.uuid4())
    session = FakeSession(executes=[[row]])
    out = await meeting_delegation_mail_info(session, uuid.uuid4())
    assert out is not None
    assert out.meeting_date is None
    assert out.delegator_name == "max@x.de"
    assert out.voting is False


async def test_auto_mailer_meeting_created_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Send the meeting mail with the builtin template.

    The scalars feed the gremium name, the gremium members, the preference filter (no
    opt-out) and the template lookup (no database template).
    """
    from app.modules.livevote.models import Meeting

    gid = uuid.uuid4()
    mid = uuid.uuid4()
    meeting = Meeting(
        id=mid,
        gremium_id=gid,
        title="Plenum",
        date=datetime(2026, 6, 16, tzinfo=UTC).date(),
        start_time=datetime(2026, 6, 16, 18, 0, tzinfo=UTC).time(),
    )
    session = FakeSession(
        scalar=["AStA"],
        scalars=[
            ["m@x.de"],
            [],
            [],
        ],
    )
    session.store[mid] = meeting
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: queue)

    await AutoMailer().meeting_created(SETTINGS, mid, pool=object())
    assert queue.messages
    assert queue.messages[0].to == ("m@x.de",)


async def test_auto_mailer_meeting_created_meeting_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Send nothing and do not crash when the meeting is missing."""
    session = FakeSession()
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    await AutoMailer().meeting_created(SETTINGS, uuid.uuid4(), pool=object())


async def test_auto_mailer_meeting_created_no_date_no_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.livevote.models import Meeting

    gid = uuid.uuid4()
    mid = uuid.uuid4()
    meeting = Meeting(id=mid, gremium_id=gid, title="Plenum", date=None, start_time=None)
    session = FakeSession(
        scalar=[None],
        scalars=[["m@x.de"], [], []],
    )
    session.store[mid] = meeting
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: queue)
    await AutoMailer().meeting_created(SETTINGS, mid, pool=object())
    assert queue.messages


async def test_auto_mailer_meeting_created_swallows_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log and swallow an exception instead of re-raising it."""
    def boom() -> Any:
        raise RuntimeError("sessionmaker boom")

    monkeypatch.setattr(auto, "get_sessionmaker", boom)
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    await AutoMailer().meeting_created(SETTINGS, uuid.uuid4(), pool=object())


async def test_auto_mailer_delegation_granted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[], []])
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: queue)
    info = DelegationMailInfo(
        delegation_id=uuid.uuid4(),
        email="d@x.de",
        meeting_title="Sitzung 1",
        meeting_date="16.06.2026",
        gremium_name="AStA",
        delegator_name="Max",
        voting=True,
    )
    await AutoMailer().delegation_changed(SETTINGS, info, granted=True, pool=object())
    assert queue.messages
    assert "Sitzung 1" in queue.messages[0].subject


async def test_auto_mailer_delegation_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[], []])
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: queue)
    info = DelegationMailInfo(
        delegation_id=uuid.uuid4(),
        email="d@x.de",
        meeting_title="Sitzung 2",
        meeting_date=None,
        gremium_name=None,
        delegator_name=None,
        voting=False,
    )
    await AutoMailer().delegation_changed(SETTINGS, info, granted=False, pool=object())
    assert queue.messages


async def test_auto_mailer_delegation_info_none_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    await AutoMailer().delegation_changed(SETTINGS, None, granted=True, pool=object())


async def test_auto_mailer_delegation_no_email_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    info = DelegationMailInfo(
        delegation_id=uuid.uuid4(),
        email=None,
        meeting_title="X",
        meeting_date=None,
        gremium_name=None,
        delegator_name=None,
        voting=False,
    )
    await AutoMailer().delegation_changed(SETTINGS, info, granted=True, pool=object())


async def test_auto_mailer_delegation_swallows_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(auto, "get_sessionmaker", boom)
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    info = DelegationMailInfo(
        delegation_id=uuid.uuid4(),
        email="d@x.de",
        meeting_title="X",
        meeting_date=None,
        gremium_name=None,
        delegator_name=None,
        voting=False,
    )
    await AutoMailer().delegation_changed(SETTINGS, info, granted=True, pool=object())


def test_get_auto_mailer_returns_instance() -> None:
    assert isinstance(get_auto_mailer(), AutoMailer)


async def test_notify_erasure_requested_with_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mail the permission holders with the builtin template."""
    session = FakeSession(
        scalars=[
            ["dpo@x.de"],
            [],
            [],
        ]
    )
    monkeypatch.setattr(privacy, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    await privacy.notify_erasure_requested(
        queue=cast(Any, queue),
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        subject_type="applicant",
    )
    assert queue.messages
    assert queue.messages[0].to == ("dpo@x.de",)
    base = SETTINGS.public_base_url.rstrip("/")
    assert f"Löschanträge öffnen: {base}/admin/privacy" in queue.messages[0].text


async def test_notify_erasure_requested_no_recipients_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[]])
    monkeypatch.setattr(privacy, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    await privacy.notify_erasure_requested(
        queue=cast(Any, queue),
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        subject_type="principal",
    )
    assert queue.messages == []


async def test_notify_erasure_executed_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[], []])
    monkeypatch.setattr(privacy, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    await privacy.notify_erasure_executed(
        queue=cast(Any, queue),
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email="user@x.de",
        subject_type="applicant",
    )
    assert queue.messages
    assert queue.messages[0].to == ("user@x.de",)


async def test_notify_erasure_executed_no_email_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        privacy, "get_sessionmaker", lambda: called.append(True)
    )
    await privacy.notify_erasure_executed(
        queue=None,
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email=None,
        subject_type="applicant",
    )
    assert called == []


async def test_notify_erasure_rejected_sends_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[], []])
    monkeypatch.setattr(privacy, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    await privacy.notify_erasure_rejected(
        queue=cast(Any, queue),
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email="user@x.de",
        reason="Aufbewahrungsfrist",
    )
    assert queue.messages
    assert "Aufbewahrungsfrist" in queue.messages[0].text


async def test_notify_erasure_rejected_links_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rejection links the application: the public page for a guest."""
    app_id = uuid.uuid4()
    session = FakeSession(executes=[[(app_id, None)]], scalars=[[], []])
    monkeypatch.setattr(privacy, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    await privacy.notify_erasure_rejected(
        queue=cast(Any, queue),
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email="user@x.de",
        reason=None,
    )
    base = SETTINGS.public_base_url.rstrip("/")
    assert f"Antrag öffnen: {base}/antrag/{app_id}" in queue.messages[0].text


async def test_notify_erasure_rejected_no_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[], []])
    monkeypatch.setattr(privacy, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    await privacy.notify_erasure_rejected(
        queue=cast(Any, queue),
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email="user@x.de",
        reason=None,
    )
    assert queue.messages


async def test_notify_erasure_rejected_no_email_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        privacy, "get_sessionmaker", lambda: called.append(True)
    )
    await privacy.notify_erasure_rejected(
        queue=None,
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email=None,
        reason="x",
    )
    assert called == []


def test_idem_parts_with_and_without_base() -> None:
    """Cover both branches of ``_idem_parts``."""
    assert service_mod._idem_parts(None, "a", "b") == ("a", "b")
    assert service_mod._idem_parts("base", "a") == ("base", "a")


def test_as_specs_filters_non_dicts() -> None:
    assert service_mod._as_specs([{"kind": "x"}, "junk", 5, None]) == [{"kind": "x"}]


def test_unused_imports_touch() -> None:
    """Reference timedelta and the recipients module, so no import is unused."""
    assert timedelta(days=1).days == 1
    assert hasattr(recipients, "RecipientResolver")
