"""Notifications-Service (T-18): Template-CRUD, `notify`-Action, Magic-Link.

Bündelt die Bausteine (Resolver, Templating, Queue) an DB + Settings:

* CRUD für `mail_template` (+ Vorschau).
* :meth:`handle_notify_action` — Flow-Action-Handler `notify` (T-14 ruft hier auf).
* :meth:`send_magic_link` — ersetzt den T-10-Platzhalter-Deliver (echte Mail).

Versand erfolgt nie synchron in der API: der Service *enqueued* nur; der arq-Worker
sendet. Fehlt die Queue (kein Redis), wird geloggt + übersprungen (kein Block, 202).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.layout import (
    reason_text,
    render_layout,
    text_to_html,
)
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.models import (
    MailTemplate,
    NotificationPreference,
    NotificationSettings,
)
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.schemas import (
    MailPreviewOut,
    MailPreviewRequest,
    MailTemplateCreate,
    MailTemplateOut,
    MailTemplateUpdate,
)
from app.modules.notifications.templating import RenderedMail, TemplateRenderError, render_mail
from app.settings import Settings, get_settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

logger = logging.getLogger("app.notifications")

MAGIC_LINK_TEMPLATE_KEY = "magic_link"

# Built-in-Fallback, falls kein `magic_link`-Template in der DB liegt (DEV/Bootstrap).
_BUILTIN_MAGIC_LINK_SUBJECT = {
    "de": "Ihr Zugangslink zur Antragsplattform",
    "en": "Your access link for the application platform",
}
_BUILTIN_MAGIC_LINK_BODY = {
    "de": "Hallo,\n\nüber diesen Link gelangen Sie zu Ihrem Antrag:\n{{ link }}\n\n"
    "Der Link ist zeitlich begrenzt gültig. Wenn Sie das nicht angefordert haben, "
    "ignorieren Sie diese Mail.\n",
    "en": "Hello,\n\nuse this link to access your application:\n{{ link }}\n\n"
    "The link is valid for a limited time. If you did not request it, ignore this "
    "email.\n",
}

# Default-Template einer ``notify``-Action ohne explizites ``templateKey`` (der
# Flow-Editor speichert die Action oft nur mit Empfängern). Existiert das Template
# nicht, greift der var-freie Builtin-Fallback (StrictUndefined-sicher).
DEFAULT_NOTIFY_TEMPLATE_KEY = "status_update"
_BUILTIN_NOTIFY_SUBJECT = {
    "de": "Aktualisierung zu Ihrem Antrag",
    "en": "Update on your application",
}
# Nennt Antragstitel + neuen Status, sofern der Dispatcher sie liefert (#4).
_BUILTIN_NOTIFY_BODY = {
    "de": "Hallo,\n\nes gibt eine Aktualisierung zu Ihrem Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}."
    "{% if status %}\n\nNeuer Status: {{ status }}{% endif %}\n",
    "en": "Hello,\n\nthere is an update on your application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}.'
    "{% if status %}\n\nNew status: {{ status }}{% endif %}\n",
}


class NotificationService:
    """DB-gestützte Notifications-Operationen (an eine `AsyncSession` gebunden)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        queue: MailQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.queue = queue
        self.settings = settings or get_settings()
        self.resolver = RecipientResolver(session)

    # ------------------------------------------------------------- templates #
    async def create_template(self, payload: MailTemplateCreate) -> MailTemplateOut:
        existing = await self._get_template_by_key(payload.key)
        if existing is not None:
            raise ConflictError(f"mail template {payload.key!r} already exists")
        tpl = MailTemplate(
            key=payload.key,
            subject_i18n=payload.subject_i18n,
            body_i18n=payload.body_i18n,
            body_html_i18n=payload.body_html_i18n,
            placeholders=payload.placeholders,
        )
        self.session.add(tpl)
        await self.session.commit()
        return _template_out(tpl)

    async def list_templates(self) -> list[MailTemplateOut]:
        rows = (
            await self.session.scalars(select(MailTemplate).order_by(MailTemplate.key))
        ).all()
        return [_template_out(t) for t in rows]

    async def update_template(
        self, template_id: uuid.UUID, payload: MailTemplateUpdate
    ) -> MailTemplateOut:
        tpl = await self.session.get(MailTemplate, template_id)
        if tpl is None:
            raise NotFoundError(f"mail template {template_id} not found")
        if payload.subject_i18n is not None:
            tpl.subject_i18n = payload.subject_i18n
        if payload.body_i18n is not None:
            tpl.body_i18n = payload.body_i18n
        if payload.body_html_i18n is not None:
            tpl.body_html_i18n = payload.body_html_i18n
        if payload.placeholders is not None:
            tpl.placeholders = payload.placeholders
        await self.session.commit()
        return _template_out(tpl)

    async def preview_template(
        self, template_id: uuid.UUID, req: MailPreviewRequest
    ) -> MailPreviewOut:
        tpl = await self.session.get(MailTemplate, template_id)
        if tpl is None:
            raise NotFoundError(f"mail template {template_id} not found")
        try:
            rendered = self._render(tpl, context=req.context, lang=req.lang)
        except TemplateRenderError as exc:
            raise ValidationProblem(
                "Template render failed.",
                errors=[{"field": "context", "msg": str(exc)}],
            ) from exc
        return MailPreviewOut(
            subject=rendered.subject,
            text=rendered.text,
            html=rendered.html,
            lang=rendered.lang,
        )

    # -------------------------------------------------------------- settings #
    async def get_notification_settings(self) -> NotificationSettings:
        """Plattform-Config lesen (Single-Row, fehlende Zeile → Defaults anlegen)."""
        row = await self.session.get(NotificationSettings, 1)
        if row is None:
            row = NotificationSettings(id=1)
            self.session.add(row)
            await self.session.commit()
            await self.session.refresh(row)
        return row

    async def update_notification_settings(
        self,
        *,
        actor: str,
        task_reminder_enabled: bool | None = None,
        task_reminder_after_days: int | None = None,
        task_reminder_repeat_days: int | None = None,
    ) -> NotificationSettings:
        """Plattform-Config ändern (Teil-Update) + Audit (CONFIG_CHANGE)."""
        from app.modules.audit.actions import AuditAction
        from app.modules.audit.service import record as audit_record

        row = await self.get_notification_settings()
        if task_reminder_enabled is not None:
            row.task_reminder_enabled = task_reminder_enabled
        if task_reminder_after_days is not None:
            row.task_reminder_after_days = task_reminder_after_days
        if task_reminder_repeat_days is not None:
            row.task_reminder_repeat_days = task_reminder_repeat_days
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type="notification_settings",
            target_id="1",
            data={
                "taskReminderEnabled": row.task_reminder_enabled,
                "taskReminderAfterDays": row.task_reminder_after_days,
                "taskReminderRepeatDays": row.task_reminder_repeat_days,
            },
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    # ----------------------------------------------------------- preferences #
    async def get_preferences(self, principal_sub: str) -> list[tuple[str, bool]]:
        """Effektive Schalter des Users — voller Katalog, Abweichungen gemerged."""
        principal_id = await self._principal_id(principal_sub)
        stored: dict[str, bool] = {}
        if principal_id is not None:
            rows = (
                await self.session.execute(
                    select(
                        NotificationPreference.kind, NotificationPreference.enabled
                    ).where(NotificationPreference.principal_id == principal_id)
                )
            ).all()
            stored = {kind: enabled for kind, enabled in rows}
        return [(k, stored.get(k, True)) for k in NOTIFICATION_KINDS]

    async def set_preferences(
        self, principal_sub: str, items: list[tuple[str, bool]]
    ) -> list[tuple[str, bool]]:
        """Bulk-Upsert der eigenen Schalter; nur Abweichungen werden gespeichert."""
        unknown = sorted({k for k, _ in items} - set(NOTIFICATION_KINDS))
        if unknown:
            raise ValidationProblem(
                "Unknown notification kinds.",
                errors=[{"field": "preferences", "msg": f"unknown: {unknown}"}],
            )
        principal_id = await self._principal_id(principal_sub)
        if principal_id is None:
            raise NotFoundError(f"principal {principal_sub!r} not found")
        for kind, enabled in items:
            row = await self.session.get(
                NotificationPreference, (principal_id, kind)
            )
            if enabled:
                if row is not None:
                    await self.session.delete(row)
            elif row is None:
                self.session.add(
                    NotificationPreference(
                        principal_id=principal_id, kind=kind, enabled=False
                    )
                )
            else:
                row.enabled = False
        await self.session.commit()
        return await self.get_preferences(principal_sub)

    async def _principal_id(self, sub: str) -> uuid.UUID | None:
        from app.modules.auth.models import Principal as PrincipalRow

        return await self.session.scalar(
            select(PrincipalRow.id).where(PrincipalRow.sub == sub)
        )

    async def send_kind_mail(
        self,
        recipients: list[str],
        *,
        kind: str,
        template_key: str,
        builtin_subject: dict[str, str],
        builtin_body: dict[str, str],
        context: dict[str, Any],
        idempotency_parts: tuple[str, ...],
        lang: str | None = None,
    ) -> bool:
        """Generischer Versand einer Benachrichtigungs-Art (#4-3).

        Filtert abgewählte Empfänger (#4-2), bevorzugt das DB-Template
        ``template_key`` (Builtin-Fallback) und hüllt die Mail ins Layout."""
        recipients = await filter_recipients_by_preference(
            self.session, recipients, kind
        )
        if not recipients:
            return False
        tpl = await self._get_template_by_key(template_key)
        if tpl is not None:
            return await self._render_and_enqueue(
                tpl,
                recipients,
                context=context,
                lang=lang,
                idempotency_parts=idempotency_parts,
                reason=kind,
            )
        try:
            rendered = render_mail(
                subject_i18n=builtin_subject,
                body_i18n=builtin_body,
                context=context,
                lang=lang or self.settings.mail_default_lang,
                default_lang=self.settings.mail_default_lang,
            )
        except TemplateRenderError as exc:  # defensiv — Builtins decken ihre Vars
            logger.warning("builtin template %r render failed: %s", template_key, exc)
            return False
        msg = MailMessage(
            to=tuple(recipients),
            subject=rendered.subject,
            text=rendered.text,
            html=self._layout_html(rendered, kind),
            idempotency_key=compute_idempotency_key(*idempotency_parts),
        )
        return await self._enqueue(msg)

    # -------------------------------------------------------------- dispatch #
    async def handle_notify_action(
        self,
        action: dict[str, Any],
        *,
        application_id: uuid.UUID | None = None,
        application_type_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
        lang: str | None = None,
        idempotency_base: str | None = None,
    ) -> int:
        """Flow-Action-Handler `notify` (T-14 dispatch).

        Ad-hoc-Modus: ``{"type":"notify","templateKey":"...","recipients":[...]}``.
        """
        # Ohne explizites `templateKey` (Flow-Editor speichert die Action häufig nur mit
        # Empfängern) das Default-Template `status_update` nutzen — sonst würde jede
        # notify-Action still verworfen (Ursache »keine Mails«).
        template_key = (
            action.get("templateKey")
            or action.get("template_key")
            or DEFAULT_NOTIFY_TEMPLATE_KEY
        )
        reason = "deadline" if "deadline" in str(template_key) else "status_update"
        recipients = await self.resolver.resolve(
            _as_specs(action.get("recipients", [])), application_id=application_id
        )
        # Abgewählte Benachrichtigungs-Arten respektieren (#4-2).
        recipients = await filter_recipients_by_preference(
            self.session, recipients, reason
        )
        if not recipients:
            logger.info("notify action resolved no recipients — skipped")
            return 0
        # Builtin-/Status-Templates referenzieren Titel + Status; nicht jeder
        # Aufrufer (Deadline-Worker, Alt-Flows) liefert sie → leere Defaults,
        # damit StrictUndefined nicht den Versand kippt.
        context = dict(context or {})
        context.setdefault("applicationTitle", "")
        context.setdefault("status", "")
        idem = _idem_parts(
            idempotency_base, "notify", str(application_id or ""), str(template_key)
        )
        tpl = await self._get_template_by_key(str(template_key))
        if tpl is not None:
            ok = await self._render_and_enqueue(
                tpl,
                recipients,
                context=context,
                lang=lang,
                idempotency_parts=idem,
                reason=reason,
            )
            return int(ok)
        # Template fehlt in der DB → Builtin-Fallback (Defaults oben decken die Vars).
        rendered = render_mail(
            subject_i18n=_BUILTIN_NOTIFY_SUBJECT,
            body_i18n=_BUILTIN_NOTIFY_BODY,
            context=context,
            lang=lang or self.settings.mail_default_lang,
            default_lang=self.settings.mail_default_lang,
        )
        msg = MailMessage(
            to=tuple(recipients),
            subject=rendered.subject,
            text=rendered.text,
            html=self._layout_html(rendered, reason),
            idempotency_key=compute_idempotency_key(*idem),
        )
        return int(await self._enqueue(msg))

    async def send_magic_link(self, *, email: str, link: str) -> None:
        """Magic-Link-Mail rendern + enqueuen (ersetzt T-10-Platzhalter)."""
        tpl = await self._get_template_by_key(MAGIC_LINK_TEMPLATE_KEY)
        if tpl is not None:
            rendered = self._render(tpl, context={"link": link}, lang=None)
        else:
            rendered = render_mail(
                subject_i18n=_BUILTIN_MAGIC_LINK_SUBJECT,
                body_i18n=_BUILTIN_MAGIC_LINK_BODY,
                context={"link": link},
                lang=self.settings.mail_default_lang,
                default_lang=self.settings.mail_default_lang,
            )
        msg = MailMessage(
            to=(email,),
            subject=rendered.subject,
            text=rendered.text,
            html=self._layout_html(rendered, "magic_link"),
            idempotency_key=compute_idempotency_key("magic_link", email, link),
        )
        await self._enqueue(msg)

    # -------------------------------------------------------------- internal #
    async def _get_template_by_key(self, key: str) -> MailTemplate | None:
        return (
            await self.session.scalars(
                select(MailTemplate).where(MailTemplate.key == key)
            )
        ).first()

    def _render(
        self, tpl: MailTemplate, *, context: dict[str, Any], lang: str | None
    ) -> RenderedMail:
        return render_mail(
            subject_i18n=tpl.subject_i18n,
            body_i18n=tpl.body_i18n,
            body_html_i18n=tpl.body_html_i18n or None,
            context=context,
            lang=lang or self.settings.mail_default_lang,
            default_lang=self.settings.mail_default_lang,
        )

    def _layout_html(self, rendered: RenderedMail, reason: str) -> str:
        """HTML-Alternative im gebrandeten Layout (#4).

        Template-HTML (autoescaped gerendert) wird als Inhalt übernommen; fehlt
        es, wird der Text-Body escaped umgebrochen — jede Mail hat damit eine
        konsistente HTML-Fassung samt Footer („warum erhalte ich das")."""
        inner = rendered.html or text_to_html(rendered.text)
        return render_layout(
            content_html=inner,
            title=rendered.subject,
            site_name=self.settings.mail_from_name,
            base_url=self.settings.public_base_url,
            reason=reason_text(reason, rendered.lang),
            lang=rendered.lang,
        )

    async def _render_and_enqueue(
        self,
        tpl: MailTemplate,
        recipients: list[str],
        *,
        context: dict[str, Any],
        lang: str | None,
        idempotency_parts: tuple[str, ...],
        reason: str = "generic",
    ) -> bool:
        """Rendern + enqueuen. `False`, wenn nichts versandt (keine Empfänger/Render-Fehler)."""
        if not recipients:
            return False
        try:
            rendered = self._render(tpl, context=context, lang=lang)
        except TemplateRenderError as exc:
            logger.warning("template %r render failed: %s", tpl.key, exc)
            return False
        msg = MailMessage(
            to=tuple(recipients),
            subject=rendered.subject,
            text=rendered.text,
            html=self._layout_html(rendered, reason),
            idempotency_key=compute_idempotency_key(*idempotency_parts),
        )
        return await self._enqueue(msg)

    async def _enqueue(self, msg: MailMessage) -> bool:
        if self.queue is None:
            logger.warning(
                "mail queue unavailable — message dropped (domains=%s)",
                msg.recipient_domains(),
            )
            return False
        await self.queue.enqueue(msg)
        return True


async def filter_recipients_by_preference(
    session: AsyncSession, recipients: list[str], kind: str
) -> list[str]:
    """Empfänger entfernen, die ``kind`` abgewählt haben (#4-2).

    Abgleich über die Principal-Mail (CITEXT, case-insensitiv). Adressen ohne
    Account (anonyme Antragsteller, Verteiler) haben keine Präferenz → bleiben.
    Unbekannte Kinds filtern nie (fail-open beim Versand)."""
    if not recipients or kind not in NOTIFICATION_KINDS:
        return recipients
    from app.modules.auth.models import Principal as PrincipalRow

    disabled = (
        await session.scalars(
            select(PrincipalRow.email)
            .join(
                NotificationPreference,
                NotificationPreference.principal_id == PrincipalRow.id,
            )
            .where(
                NotificationPreference.kind == kind,
                NotificationPreference.enabled.is_(False),
                PrincipalRow.email.in_(recipients),
            )
        )
    ).all()
    blocked = {e.lower() for e in disabled if e}
    return [r for r in recipients if r.lower() not in blocked]


def _idem_parts(base: str | None, *parts: str) -> tuple[str, ...]:
    """Idempotenz-Bestandteile mit optionaler Basis (z. B. Flow-Action-Key)."""
    return (base, *parts) if base else parts


def _as_specs(raw: list[Any]) -> list[dict[str, Any]]:
    """Recipient-Rohdaten (JSONB-Liste) → Liste von Dicts (defensiv)."""
    return [r for r in raw if isinstance(r, dict)]


def _template_out(tpl: MailTemplate) -> MailTemplateOut:
    return MailTemplateOut(
        id=tpl.id,
        key=tpl.key,
        subject_i18n=tpl.subject_i18n,
        body_i18n=tpl.body_i18n,
        body_html_i18n=tpl.body_html_i18n,
        placeholders=tpl.placeholders,
    )
