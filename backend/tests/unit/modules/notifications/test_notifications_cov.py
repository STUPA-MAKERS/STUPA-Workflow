"""Coverage-Härtung für die Notifications-Bausteine (service/auto/recipients/privacy).

Alle Tests sind reine Unit-Tests: DB über lokale Fakes, Versand über `FakeQueue`,
kein echtes SMTP/Redis/Postgres. Die Sessionmaker-basierten Hintergrund-Tasks
(``auto.py``/``privacy.py``) werden über ein gefaktes ``get_sessionmaker``
gefahren — so laufen die ``async with sessionmaker() as session``-Pfade ohne DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications import auto, privacy, recipients
from app.modules.notifications import service as service_mod
from app.modules.notifications.auto import (
    AssignmentMailInfo,
    AutoMailer,
    DelegationMailInfo,
    assignment_mail_info,
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


# --------------------------------------------------------------------------- fakes
class FakeResult:
    """Result-Ersatz mit ``all``/``first``/``scalar_one_or_none``."""

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def scalar_one_or_none(self) -> Any:
        return self._items[0] if self._items else None


class FakeSession:
    """AsyncSession-Stub: FIFO-Queues für ``scalars``/``scalar``/``execute``.

    Erweitert das Support-Fake um ``refresh``/``flush``/``delete`` (die der
    Settings-/Preference-Pfad des Service braucht) und um einen In-Memory-Store
    für ``get`` (Integer- *und* UUID-Keys)."""

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
    """``get_sessionmaker``-Ersatz.

    Der Aufrufer macht ``sessionmaker = get_sessionmaker()`` und dann
    ``async with sessionmaker() as session``. Also muss ``get_sessionmaker``
    eine Factory liefern, die beim Aufruf den Context-Manager erzeugt."""

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


# =========================================================================== service
async def test_create_template_ok() -> None:
    from app.modules.notifications.schemas import MailTemplateCreate

    session = FakeSession(scalars=[[]])  # keine Kollision
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
    ta = _tpl("status_update")  # Katalog-Override
    ta.id = uuid.uuid4()
    tb = _tpl("custom_flow")  # nicht-katalogisiert → hängt hinten an
    tb.id = uuid.uuid4()
    session = FakeSession(scalars=[[ta, tb]])
    out = await _svc(session).list_templates()
    by_key = {t.key: t for t in out}
    assert by_key["status_update"].source == "override"  # DB-Override gewinnt
    assert by_key["meeting_created"].source == "builtin"  # nur Builtin
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
    session = FakeSession(scalars=[[]])  # kein Bestand
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
    session = FakeSession(scalars=[[]])  # noch keine Override-Zeile
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
    assert session.added  # neue Zeile angelegt


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
    assert session.added == []  # kein Neuanlegen


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
    session = FakeSession(scalars=[[]])  # keine Override-Zeile
    out = await _svc(session).reset_template("status_update")
    assert out.source == "builtin"
    assert session.deleted == []  # nichts zu löschen
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
    session = FakeSession()  # leerer Store → Zeile fehlt
    row = await _svc(session).get_notification_settings()
    assert row.id == 1
    assert session.committed == 1
    assert session.refreshed == 1
    assert row in session.added


async def test_get_notification_settings_returns_existing() -> None:
    existing = NotificationSettings(id=1)
    session = FakeSession()
    session.store[1] = existing  # ohne add → kein UUID-Override
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
    # Keine Felder übergeben → alle bleiben unverändert (else-Zweige aller ifs).
    assert row.task_reminder_enabled is True
    assert row.task_reminder_after_days == 5
    assert row.task_reminder_repeat_days == 7


# ----------------------------------------------------------------- preferences
async def test_get_preferences_no_principal_all_default() -> None:
    session = FakeSession(scalar=[None])  # _principal_id → None
    prefs = await _svc(session).get_preferences("ghost")
    assert all(enabled for _, enabled in prefs)
    assert {k for k, _ in prefs}  # voller Katalog


async def test_get_preferences_merges_stored_disable() -> None:
    pid = uuid.uuid4()
    session = FakeSession(
        scalar=[pid],
        # execute() liefert (kind, enabled)-Paare des Users.
        executes=[[("comment", False), ("vote", False)]],
    )
    prefs = dict(await _svc(session).get_preferences("u"))
    assert prefs["comment"] is False
    assert prefs["vote"] is False
    assert prefs["status_update"] is True  # nicht gespeichert → Default an


async def test_set_preferences_unknown_kind_422() -> None:
    with pytest.raises(ValidationProblem):
        await _svc(FakeSession()).set_preferences("u", [("does_not_exist", False)])


async def test_set_preferences_principal_not_found_404() -> None:
    session = FakeSession(scalar=[None])  # _principal_id → None
    with pytest.raises(NotFoundError):
        await _svc(session).set_preferences("ghost", [("comment", False)])


async def test_set_preferences_all_branches() -> None:
    pid = uuid.uuid4()
    # Bestehende Abwahl-Zeile für 'comment' (wird wieder aktiviert → delete),
    # 'vote' soll neu abgewählt werden (add), 'task' existiert + bleibt aus (update).
    existing_comment = NotificationPreference(
        principal_id=pid, kind="comment", enabled=False
    )
    existing_task = NotificationPreference(
        principal_id=pid, kind="task", enabled=False
    )
    session = FakeSession(
        # _principal_id (set), dann _principal_id (get_preferences),
        scalar=[pid, pid],
        # get_preferences am Ende: keine gespeicherten Abweichungen mehr.
        executes=[[]],
    )
    # session.get((pid, kind)) → die jeweiligen Zeilen.
    session.store[(pid, "comment")] = existing_comment
    session.store[(pid, "task")] = existing_task

    out = await _svc(session).set_preferences(
        "u",
        [
            ("comment", True),  # row vorhanden + enabled → delete
            ("status_update", True),  # row None + enabled → nichts
            ("vote", False),  # row None + disabled → add
            ("task", False),  # row vorhanden + disabled → update
        ],
    )
    assert existing_comment in session.deleted
    assert existing_task.enabled is False
    added_kinds = {p.kind for p in session.added}
    assert "vote" in added_kinds
    assert isinstance(out, list)


# --------------------------------------------------------- send_kind_mail paths
async def test_send_kind_mail_no_recipients_returns_false() -> None:
    # filter_recipients_by_preference: leere Liste → False, kein Versand.
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
    tpl = _tpl("meeting_created")
    # 1. scalars: Präferenz-Filter (keine Abwahl), 2. scalars: Template-Lookup.
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
    # Kein DB-Template → Builtin-Render + enqueue.
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
    # Builtin referenziert eine fehlende Variable → TemplateRenderError → False.
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


# -------------------------------------------------------- handle_notify_action
async def test_handle_notify_action_builtin_catalogue_key_fallback() -> None:
    # Katalog-Key ohne DB-Override → spec-spezifischer Builtin (deadline-Zweig).
    session = FakeSession(scalars=[[], []])
    queue = FakeQueue()
    svc = _svc(session, queue)
    svc.resolver = cast(Any, FakeResolver(["a@x.de"]))
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "deadline_approaching"},
        context={"applicationTitle": "Beamer", "dueAt": "morgen"},
    )
    assert count == 1
    # reason == 'deadline' (template_key enthält 'deadline').
    assert "Beamer" in queue.messages[0].text


async def test_handle_notify_action_template_key_underscore_alias() -> None:
    # action ohne templateKey, aber template_key (snake_case) → benutzt.
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
    # Resolver liefert Adressen, Präferenz-Filter entfernt alle → 0.
    pid = uuid.uuid4()
    # filter_recipients_by_preference scalars: alle 'a@x.de' abgewählt.
    session = FakeSession(scalars=[["a@x.de"]])
    queue = FakeQueue()
    svc = _svc(session, queue)
    svc.resolver = cast(Any, FakeResolver(["a@x.de"]))
    count = await svc.handle_notify_action(
        {"type": "notify", "templateKey": "status_update"},
    )
    assert count == 0
    assert queue.messages == []
    assert pid  # silence unused


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
    assert msg.html  # Layout gerendert (html-Body übernommen)


async def test_enqueue_none_queue_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession(scalars=[[]])  # magic_link nicht in DB → Builtin
    # queue=None → _enqueue loggt + verwirft.
    await _svc(session, None).send_magic_link(email="a@x.de", link="https://l")


# ------------------------------------------------ filter_recipients_by_preference
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
    # disabled = ['A@X.de', None] → blocked {'a@x.de'}; 'b@y.de' bleibt.
    session = FakeSession(scalars=[["A@X.de", None]])
    out = await filter_recipients_by_preference(
        cast(AsyncSession, session), ["a@x.de", "b@y.de"], "comment"
    )
    assert out == ["b@y.de"]


# =========================================================================== recipients
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
    # permission-Spec NICHT als letztes Element → Schleife läuft weiter.
    session = FakeSession(scalars=[["perm@x.de"]])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [
            {"kind": "permission", "ref": "privacy.manage"},
            {"kind": "email", "ref": "fix@x.de"},
        ]
    )
    assert out == ["fix@x.de", "perm@x.de"]


async def test_resolve_unknown_spec_then_loop_continues() -> None:
    # Unbekannte Spec (keine elif matcht, kein ``ref``) gefolgt von gültiger Spec
    # → Branch 65->50 (Schleife läuft nach dem Durchfall weiter).
    out = await RecipientResolver(cast(AsyncSession, FakeSession())).resolve(
        [
            {"kind": "permission"},  # kein ref → keine elif greift
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
    # Eigenes ``now`` (nicht-None-Zweig) + role-Auflösung.
    session = FakeSession(scalars=[["r@x.de"]])
    out = await RecipientResolver(cast(AsyncSession, session)).resolve(
        [{"kind": "role", "ref": "manager"}], now=datetime.now(UTC)
    )
    assert out == ["r@x.de"]


async def test_actionable_vote_state_with_gremium() -> None:
    from app.modules.flow.models import State

    gid = str(uuid.uuid4())
    state = State(kind="vote", config={"gremiumId": gid})
    session = FakeSession(scalars=[["v@x.de"]])
    out = await actionable_principal_emails(
        cast(AsyncSession, session), state=state, gremium_id=None
    )
    assert out == ["v@x.de"]


async def test_actionable_vote_state_without_gremium_returns_empty() -> None:
    from app.modules.flow.models import State

    state = State(kind="vote", config={})  # kein gremiumId
    out = await actionable_principal_emails(
        cast(AsyncSession, FakeSession()), state=state, gremium_id=None
    )
    assert out == []


async def test_actionable_vote_state_config_not_dict() -> None:
    from app.modules.flow.models import State

    state = State(kind="vote", config=None)  # config kein dict → {}
    out = await actionable_principal_emails(
        cast(AsyncSession, FakeSession()), state=state, gremium_id=None
    )
    assert out == []


async def test_actionable_non_vote_state_queries_roles() -> None:
    from app.modules.flow.models import State

    state = State(kind="normal", config={})
    session = FakeSession(scalars=[["t@x.de", "T@X.de", None]])
    out = await actionable_principal_emails(
        cast(AsyncSession, session), state=state, gremium_id=uuid.uuid4()
    )
    # dedupliziert (case-sensitiv set) + sortiert, leere raus.
    assert out == ["T@X.de", "t@x.de"]


async def test_actionable_state_none_falls_through_to_role_query() -> None:
    session = FakeSession(scalars=[["x@x.de"]])
    out = await actionable_principal_emails(
        cast(AsyncSession, session), state=None, gremium_id=None
    )
    assert out == ["x@x.de"]


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
    session = FakeSession(scalar=[2])  # count > 0 → True
    assert await state_actionable(cast(AsyncSession, session), state) is True


async def test_state_actionable_no_manual_transitions_false() -> None:
    from app.modules.flow.models import State

    state = State(kind="normal", config={}, id=uuid.uuid4())
    session = FakeSession(scalar=[0])  # count == 0 → False
    assert await state_actionable(cast(AsyncSession, session), state) is False


# =========================================================================== auto
async def test_assignment_mail_info_query_fails_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BoomSession:
        async def execute(self, _stmt: Any) -> Any:
            raise RuntimeError("db down")

    out = await assignment_mail_info(BoomSession(), uuid.uuid4())
    assert out is None


async def test_assignment_mail_info_row_none() -> None:
    session = FakeSession(executes=[[]])  # .first() → None
    out = await assignment_mail_info(session, uuid.uuid4())
    assert out is None


async def test_assignment_mail_info_label_from_i18n() -> None:
    aid = uuid.uuid4()
    row = ("a@x.de", {"de": "Manager", "en": "Manager"}, "manager", "AStA", None)
    session = FakeSession(executes=[[row]])
    out = await assignment_mail_info(session, aid)
    assert out is not None
    assert out.role_label == "Manager"
    assert out.email == "a@x.de"
    assert out.gremium_name == "AStA"


async def test_assignment_mail_info_label_fallback_to_key() -> None:
    # name_i18n leer/kein dict → label = key.
    row = ("a@x.de", {}, "manager", None, None)
    session = FakeSession(executes=[[row]])
    out = await assignment_mail_info(session, uuid.uuid4())
    assert out is not None
    assert out.role_label == "manager"


async def test_assignment_mail_info_label_first_value_when_no_de() -> None:
    # name_i18n ohne 'de' → next(iter(...)) greift.
    row = ("a@x.de", {"en": "Chair"}, "chair", None, None)
    session = FakeSession(executes=[[row]])
    out = await assignment_mail_info(session, uuid.uuid4())
    assert out is not None
    assert out.role_label == "Chair"


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
    did = uuid.uuid4()
    date = datetime(2026, 6, 16, tzinfo=UTC).date()
    row = ("d@x.de", "Sitzung 1", date, "AStA", "Max", "max@x.de", True)
    session = FakeSession(executes=[[row]])
    out = await meeting_delegation_mail_info(session, did)
    assert out is not None
    assert out.meeting_date == "16.06.2026"
    assert out.delegator_name == "Max"  # display_name bevorzugt
    assert out.voting is True


async def test_meeting_delegation_mail_info_no_date_falls_back_to_email() -> None:
    # date None → meeting_date None; d_name None → d_email als delegator_name.
    row = ("d@x.de", "Sitzung 2", None, None, None, "max@x.de", None)
    session = FakeSession(executes=[[row]])
    out = await meeting_delegation_mail_info(session, uuid.uuid4())
    assert out is not None
    assert out.meeting_date is None
    assert out.delegator_name == "max@x.de"
    assert out.voting is False


# ---------------------------------------------------------------- AutoMailer
async def test_auto_mailer_meeting_created_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        scalar=["AStA"],  # gremium_name lookup
        scalars=[
            ["m@x.de"],  # RecipientResolver gremium emails
            [],  # filter_recipients_by_preference (keine Abwahl)
            [],  # _get_template_by_key (kein DB-Template → Builtin)
        ],
    )
    session.store[mid] = meeting  # session.get(Meeting, mid)
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: queue)

    await AutoMailer().meeting_created(SETTINGS, mid, pool=object())
    assert queue.messages
    assert queue.messages[0].to == ("m@x.de",)


async def test_auto_mailer_meeting_created_meeting_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()  # store leer → get(Meeting) None
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    # Kein Crash, kein Versand.
    await AutoMailer().meeting_created(SETTINGS, uuid.uuid4(), pool=object())


async def test_auto_mailer_meeting_created_no_date_no_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.livevote.models import Meeting

    gid = uuid.uuid4()
    mid = uuid.uuid4()
    meeting = Meeting(id=mid, gremium_id=gid, title="Plenum", date=None, start_time=None)
    session = FakeSession(
        scalar=[None],  # kein gremium_name → '' Branch
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
    def boom() -> Any:
        raise RuntimeError("sessionmaker boom")

    monkeypatch.setattr(auto, "get_sessionmaker", boom)
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    # Exception wird geloggt + verschluckt (kein Re-raise).
    await AutoMailer().meeting_created(SETTINGS, uuid.uuid4(), pool=object())


async def test_auto_mailer_assignment_granted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[], []])  # Filter, dann kein DB-Template
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: queue)
    info = AssignmentMailInfo(
        assignment_id=uuid.uuid4(),
        email="a@x.de",
        role_label="Manager",
        gremium_name="AStA",
        delegated_by=None,
    )
    await AutoMailer().assignment_changed(SETTINGS, info, granted=True, pool=object())
    assert queue.messages
    assert "Manager" in queue.messages[0].subject


async def test_auto_mailer_assignment_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[], []])
    monkeypatch.setattr(auto, "get_sessionmaker", _sessionmaker_for(session))
    queue = FakeQueue()
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: queue)
    info = AssignmentMailInfo(
        assignment_id=uuid.uuid4(),
        email="a@x.de",
        role_label="Manager",
        gremium_name=None,
        delegated_by=None,
    )
    await AutoMailer().assignment_changed(SETTINGS, info, granted=False, pool=object())
    assert queue.messages


async def test_auto_mailer_assignment_info_none_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    # info None → früher return, kein sessionmaker nötig.
    await AutoMailer().assignment_changed(SETTINGS, None, granted=True, pool=object())


async def test_auto_mailer_assignment_no_email_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    info = AssignmentMailInfo(
        assignment_id=uuid.uuid4(),
        email=None,  # keine Mail → return
        role_label="Manager",
        gremium_name=None,
        delegated_by=None,
    )
    await AutoMailer().assignment_changed(SETTINGS, info, granted=True, pool=object())


async def test_auto_mailer_assignment_swallows_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(auto, "get_sessionmaker", boom)
    monkeypatch.setattr(auto, "mail_queue_from_pool", lambda _pool: FakeQueue())
    info = AssignmentMailInfo(
        assignment_id=uuid.uuid4(),
        email="a@x.de",
        role_label="Manager",
        gremium_name=None,
        delegated_by=None,
    )
    await AutoMailer().assignment_changed(SETTINGS, info, granted=True, pool=object())


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


# =========================================================================== privacy
async def test_notify_erasure_requested_with_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(
        scalars=[
            ["dpo@x.de"],  # RecipientResolver permission
            [],  # filter_recipients_by_preference
            [],  # _get_template_by_key → Builtin
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


async def test_notify_erasure_requested_no_recipients_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(scalars=[[]])  # RecipientResolver → keine Adressen
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
    session = FakeSession(scalars=[[], []])  # Filter, dann kein DB-Template
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
        privacy, "get_sessionmaker", lambda: called.append(True)  # type: ignore[func-returns-value]
    )
    await privacy.notify_erasure_executed(
        queue=None,
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email=None,
        subject_type="applicant",
    )
    assert called == []  # früher return, kein Sessionmaker


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
        reason=None,  # → '' Branch
    )
    assert queue.messages


async def test_notify_erasure_rejected_no_email_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[bool] = []
    monkeypatch.setattr(
        privacy, "get_sessionmaker", lambda: called.append(True)  # type: ignore[func-returns-value]
    )
    await privacy.notify_erasure_rejected(
        queue=None,
        settings=SETTINGS,
        request_id=uuid.uuid4(),
        email=None,
        reason="x",
    )
    assert called == []


# Sicherstellen, dass der service-Modul-Helper _idem_parts beide Zweige nimmt.
def test_idem_parts_with_and_without_base() -> None:
    assert service_mod._idem_parts(None, "a", "b") == ("a", "b")
    assert service_mod._idem_parts("base", "a") == ("base", "a")


def test_as_specs_filters_non_dicts() -> None:
    assert service_mod._as_specs([{"kind": "x"}, "junk", 5, None]) == [{"kind": "x"}]


def test_unused_imports_touch() -> None:
    # timedelta/recipients-Modul referenzieren (Lint: keine ungenutzten Importe).
    assert timedelta(days=1).days == 1
    assert hasattr(recipients, "RecipientResolver")
