"""Notifications service: template CRUD, the `notify` action, magic link.

The service wires the building blocks (resolver, templating, queue) to the DB and the
settings:

`mail_template`: CRUD and preview.
`handle_notify_action`: the handler of the `notify` flow action.
`send_magic_link`: renders and sends the magic-link mail.

The API never sends a mail synchronously. The service only enqueues and the arq worker
sends. When the queue is missing (no Redis) the service logs the drop and skips it. It
never blocks the request.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    MailPreviewPayloadRequest,
    MailPreviewRequest,
    MailTemplateCreate,
    MailTemplateOut,
    MailTemplateUpdate,
    MailTemplateUpsert,
)
from app.modules.notifications.templating import RenderedMail, TemplateRenderError, render_mail
from app.settings import Settings, get_settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

logger = logging.getLogger("app.notifications")

MAGIC_LINK_TEMPLATE_KEY = "magic_link"

# The sender uses this builtin fallback when the DB has no `magic_link` template.
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

# Default template for a ``notify`` action without an explicit ``templateKey``.
# When the template is absent, the variable-free builtin fallback applies. That
# fallback is safe under StrictUndefined.
DEFAULT_NOTIFY_TEMPLATE_KEY = "status_update"
# Team-facing default for the non-applicant recipients of a `notify` action without an
# explicit templateKey. Applicants keep `status_update`.
TEAM_NOTIFY_TEMPLATE_KEY = "status_update_team"
_BUILTIN_NOTIFY_SUBJECT = {
    "de": "Aktualisierung zu Ihrem Antrag",
    "en": "Update on your application",
}
# The body names the application title and the new status when the dispatcher
# supplies them.
_BUILTIN_NOTIFY_BODY = {
    "de": "Hallo,\n\nes gibt eine Aktualisierung zu Ihrem Antrag"
    "{% if applicationTitle %} „{{ applicationTitle }}“{% endif %}."
    "{% if status %}\n\nNeuer Status: {{ status }}{% endif %}\n",
    "en": "Hello,\n\nthere is an update on your application"
    '{% if applicationTitle %} "{{ applicationTitle }}"{% endif %}.'
    "{% if status %}\n\nNew status: {{ status }}{% endif %}\n",
}


class NotificationService:
    """DB-backed notification operations bound to an `AsyncSession`."""

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
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # A concurrent insert of the same key (UNIQUE mail_template.key) won
            # between the read and the commit. Return 409 and not 500. The client
            # retries.
            await self.session.rollback()
            raise ConflictError(
                f"mail template {payload.key!r} already exists", code="conflict"
            ) from exc
        return _template_out(tpl)

    async def list_templates(self) -> list[MailTemplateOut]:
        """Return every mail kind, as a DB override or as the builtin default.

        The order follows the catalogue. The method appends the DB rows that are not
        in the catalogue (for example a custom flow ``templateKey``) in alphabetical
        order.
        """
        from app.modules.notifications.templates_catalogue import (
            CATALOGUE_BY_KEY,
            TEMPLATE_CATALOGUE,
        )

        rows = {
            t.key: t
            for t in (await self.session.scalars(select(MailTemplate))).all()
        }
        out: list[MailTemplateOut] = []
        for spec in TEMPLATE_CATALOGUE:
            row = rows.get(spec.key)
            if row is not None:
                out.append(_template_out(row, source="override"))
            else:
                out.append(
                    MailTemplateOut(
                        id=None,
                        key=spec.key,
                        subject_i18n=spec.subject_i18n,
                        body_i18n=spec.body_i18n,
                        body_html_i18n={},
                        placeholders=spec.placeholders,
                        source="builtin",
                    )
                )
        for key in sorted(rows):
            if key not in CATALOGUE_BY_KEY:
                out.append(_template_out(rows[key], source="override"))
        return out

    async def upsert_template(self, payload: MailTemplateUpsert) -> MailTemplateOut:
        """Create or update an override by key.

        A builtin key is allowed.

        Raises:
            ValidationProblem: The key has no catalogue entry and no existing row
                (HTTP 422).
        """
        from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY

        existing = await self._get_template_by_key(payload.key)
        if existing is None and payload.key not in CATALOGUE_BY_KEY:
            raise ValidationProblem(
                "Unknown template key.",
                errors=[{"field": "key", "msg": f"unknown: {payload.key}"}],
            )
        inserting = existing is None
        if existing is None:
            spec = CATALOGUE_BY_KEY[payload.key]
            existing = MailTemplate(
                key=payload.key,
                subject_i18n=payload.subject_i18n,
                body_i18n=payload.body_i18n,
                body_html_i18n=payload.body_html_i18n,
                placeholders=spec.placeholders,
            )
            self.session.add(existing)
        else:
            existing.subject_i18n = payload.subject_i18n
            existing.body_i18n = payload.body_i18n
            existing.body_html_i18n = payload.body_html_i18n
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # A concurrent insert of the same key (UNIQUE mail_template.key) won
            # between the read and the commit. Return 409 and not 500. The client
            # retries.
            await self.session.rollback()
            if inserting:
                raise ConflictError(
                    f"mail template {payload.key!r} already exists",
                    code="conflict",
                ) from exc
            raise
        return _template_out(existing, source="override")

    async def reset_template(self, key: str) -> MailTemplateOut:
        """Delete the override and restore the builtin default."""
        from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY

        spec = CATALOGUE_BY_KEY.get(key)
        if spec is None:
            raise NotFoundError(f"mail template {key!r} not in catalogue")
        existing = await self._get_template_by_key(key)
        if existing is not None:
            await self.session.delete(existing)
            await self.session.commit()
        return MailTemplateOut(
            id=None,
            key=spec.key,
            subject_i18n=spec.subject_i18n,
            body_i18n=spec.body_i18n,
            body_html_i18n={},
            placeholders=spec.placeholders,
            source="builtin",
        )

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

    async def preview_payload(self, req: MailPreviewPayloadRequest) -> MailPreviewOut:
        """Render a preview from an editor draft (no DB row)."""
        transient = MailTemplate(
            key="__preview__",
            subject_i18n=req.subject_i18n,
            body_i18n=req.body_i18n,
            body_html_i18n=req.body_html_i18n,
            placeholders={},
        )
        try:
            rendered = self._render(transient, context=req.context, lang=req.lang)
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

    async def get_notification_settings(self) -> NotificationSettings:
        """Read the platform config.

        The config is a single row. The method creates it with the defaults when the
        row is missing.
        """
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
        """Update the platform config partially and audit it as CONFIG_CHANGE."""
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

    async def get_preferences(self, principal_sub: str) -> list[tuple[str, bool]]:
        """Return the effective switches of the user.

        The result holds the full catalogue with the stored deviations merged in.
        """
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
        """Upsert the own switches in bulk.

        The method stores only the deviations from the default.
        """
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
        """Send one notification kind.

        The method drops the recipients that opted out. It prefers the DB template
        ``template_key`` and falls back to the builtin. It wraps the mail in the
        layout.

        Returns:
            True when the method enqueued a mail.
        """
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
        except TemplateRenderError as exc:  # defensive: builtins cover their own vars
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
        """Handle the `notify` flow action.

        Ad-hoc mode: ``{"type":"notify","templateKey":"...","recipients":[...]}``.

        Returns:
            The number of enqueued sends.
        """
        specs = _as_specs(action.get("recipients", []))
        # The builtin and status templates reference the title and the status. Not
        # every caller (deadline worker, legacy flows) supplies them. Default to empty
        # strings so StrictUndefined does not fail the send.
        context = dict(context or {})
        context.setdefault("applicationTitle", "")
        context.setdefault("status", "")
        template_key = action.get("templateKey") or action.get("template_key")
        if template_key:
            return await self._notify_send(
                template_key=str(template_key),
                specs=specs,
                application_id=application_id,
                context=context,
                lang=lang,
                idempotency_base=idempotency_base,
            )
        # No explicit templateKey. The flow editor often stores the action with
        # recipients only. Applicants get the applicant-facing default and every other
        # recipient kind gets the team-facing wording. The template key is part of the
        # idempotency parts, so the two sends get distinct keys.
        applicant_specs = [s for s in specs if s.get("kind") == "applicant"]
        team_specs = [s for s in specs if s.get("kind") != "applicant"]
        count = 0
        for partition_key, partition in (
            (DEFAULT_NOTIFY_TEMPLATE_KEY, applicant_specs),
            (TEAM_NOTIFY_TEMPLATE_KEY, team_specs),
        ):
            if not partition:
                continue
            count += await self._notify_send(
                template_key=partition_key,
                specs=partition,
                application_id=application_id,
                context=context,
                lang=lang,
                idempotency_base=idempotency_base,
            )
        return count

    async def _notify_send(
        self,
        *,
        template_key: str,
        specs: list[dict[str, Any]],
        application_id: uuid.UUID | None,
        context: dict[str, Any],
        lang: str | None,
        idempotency_base: str | None,
    ) -> int:
        """Resolve, filter and enqueue one `notify` send for ``template_key``."""
        # Derive the real notification kind from the catalogue. It drives both the
        # opt-out filter and the footer reason. A key that is unknown or DB-only falls
        # back to `status_update`.
        from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY

        spec = CATALOGUE_BY_KEY.get(template_key)
        reason = spec.kind if spec is not None else DEFAULT_NOTIFY_TEMPLATE_KEY
        recipients = await self.resolver.resolve(specs, application_id=application_id)
        recipients = await filter_recipients_by_preference(
            self.session, recipients, reason
        )
        if not recipients:
            logger.info("notify action resolved no recipients — skipped")
            return 0
        idem = _idem_parts(
            idempotency_base, "notify", str(application_id or ""), template_key
        )
        tpl = await self._get_template_by_key(template_key)
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
        # The DB holds no template, so use the builtin fallback. A catalogue key (for
        # example ``deadline_approaching``) uses its own default. Every other key uses
        # status_update.
        rendered = render_mail(
            subject_i18n=spec.subject_i18n if spec else _BUILTIN_NOTIFY_SUBJECT,
            body_i18n=spec.body_i18n if spec else _BUILTIN_NOTIFY_BODY,
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
        """Render and enqueue the magic-link mail."""
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
        """Wrap the mail content in the branded HTML layout.

        The method uses the template HTML as content. Jinja2 renders that HTML with
        autoescape. When the template has no HTML, the method escapes the text body and
        wraps it. Every mail therefore has one consistent HTML version with the footer
        that says why the reader gets it.
        """
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
        """Render the template and enqueue the mail.

        Returns:
            False when the method sends nothing, because of missing recipients or a
            render error.
        """
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
    """Drop the recipients that opted out of ``kind``.

    The match runs on the principal mail (CITEXT, case-insensitive). An address without
    an account (anonymous applicant, mailing list) has no preference and stays. An
    unknown kind never filters. The send stays fail-open.
    """
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
    """Build the idempotency parts with an optional base (for example a flow-action key)."""
    return (base, *parts) if base else parts


def _as_specs(raw: list[Any]) -> list[dict[str, Any]]:
    """Keep only the dict entries of the raw recipient data (JSONB list)."""
    return [r for r in raw if isinstance(r, dict)]


def _template_out(tpl: MailTemplate, *, source: str = "override") -> MailTemplateOut:
    return MailTemplateOut(
        id=tpl.id,
        key=tpl.key,
        subject_i18n=tpl.subject_i18n,
        body_i18n=tpl.body_i18n,
        body_html_i18n=tpl.body_html_i18n,
        placeholders=tpl.placeholders,
        source=source,  # type: ignore[arg-type]
    )
