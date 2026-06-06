"""Notifications-Service (T-18): Regel-/Template-CRUD, Event-Dispatch, `notify`.

Bündelt die Bausteine (Resolver, Templating, Queue) an DB + Settings:

* CRUD für `notification_rule` / `mail_template` (+ Vorschau).
* :meth:`dispatch_event` — je Event passende, **aktive** Regeln auswerten,
  Empfänger auflösen, Template rendern, Mail **idempotent** in die Queue legen.
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

from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.models import MailTemplate, NotificationRule
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.schemas import (
    MailPreviewOut,
    MailPreviewRequest,
    MailTemplateCreate,
    MailTemplateOut,
    MailTemplateUpdate,
    NotificationRuleCreate,
    NotificationRuleOut,
    NotificationRuleUpdate,
    RecipientSpec,
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

    # ----------------------------------------------------------------- rules #
    async def create_rule(self, payload: NotificationRuleCreate) -> NotificationRuleOut:
        rule = NotificationRule(
            event=payload.event,
            recipients=[r.model_dump(exclude_none=True) for r in payload.recipients],
            template_key=payload.template_key,
            application_type_id=payload.application_type_id,
            enabled=payload.enabled,
        )
        self.session.add(rule)
        await self.session.commit()
        return _rule_out(rule)

    async def list_rules(self) -> list[NotificationRuleOut]:
        rows = (
            await self.session.scalars(
                select(NotificationRule).order_by(NotificationRule.created_at)
            )
        ).all()
        return [_rule_out(r) for r in rows]

    async def update_rule(
        self, rule_id: uuid.UUID, payload: NotificationRuleUpdate
    ) -> NotificationRuleOut:
        rule = await self.session.get(NotificationRule, rule_id)
        if rule is None:
            raise NotFoundError(f"notification rule {rule_id} not found")
        if payload.event is not None:
            rule.event = payload.event
        if payload.recipients is not None:
            rule.recipients = [r.model_dump(exclude_none=True) for r in payload.recipients]
        if payload.template_key is not None:
            rule.template_key = payload.template_key
        if payload.application_type_id is not None:
            rule.application_type_id = payload.application_type_id
        if payload.enabled is not None:
            rule.enabled = payload.enabled
        await self.session.commit()
        return _rule_out(rule)

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

    # -------------------------------------------------------------- dispatch #
    async def dispatch_event(
        self,
        event: str,
        *,
        application_id: uuid.UUID | None = None,
        application_type_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
        lang: str | None = None,
        idempotency_base: str | None = None,
    ) -> int:
        """Aktive Regeln zum Event auswerten + Mails enqueuen. Gibt Anzahl Mails."""
        stmt = select(NotificationRule).where(
            NotificationRule.event == event,
            NotificationRule.enabled.is_(True),
        )
        rules = (await self.session.scalars(stmt)).all()
        sent = 0
        for rule in rules:
            # type-gefilterte Regel feuert nur für den passenden Antragstyp.
            if (
                rule.application_type_id is not None
                and rule.application_type_id != application_type_id
            ):
                continue
            tpl = await self._get_template_by_key(rule.template_key)
            if tpl is None:
                logger.warning(
                    "notification rule %s references missing template %r",
                    rule.id,
                    rule.template_key,
                )
                continue
            recipients = await self.resolver.resolve(
                _as_specs(rule.recipients), application_id=application_id
            )
            ok = await self._render_and_enqueue(
                tpl,
                recipients,
                context=context or {},
                lang=lang,
                idempotency_parts=_idem_parts(
                    idempotency_base, event, str(application_id or ""), str(rule.id)
                ),
            )
            sent += int(ok)
        return sent

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

        Zwei Modi:
        * ``{"type":"notify","event":"status_changed"}`` → regelbasiert (dispatch_event).
        * ``{"type":"notify","templateKey":"...","recipients":[...]}`` → ad-hoc.
        """
        event = action.get("event")
        if event:
            return await self.dispatch_event(
                str(event),
                application_id=application_id,
                application_type_id=application_type_id,
                context=context,
                lang=lang,
                idempotency_base=idempotency_base,
            )
        template_key = action.get("templateKey") or action.get("template_key")
        if not template_key:
            logger.warning("notify action without 'event' or 'templateKey' — skipped")
            return 0
        tpl = await self._get_template_by_key(str(template_key))
        if tpl is None:
            logger.warning("notify action references missing template %r", template_key)
            return 0
        recipients = await self.resolver.resolve(
            _as_specs(action.get("recipients", [])), application_id=application_id
        )
        ok = await self._render_and_enqueue(
            tpl,
            recipients,
            context=context or {},
            lang=lang,
            idempotency_parts=_idem_parts(
                idempotency_base, "notify", str(application_id or ""), str(template_key)
            ),
        )
        return int(ok)

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
            html=rendered.html,
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

    async def _render_and_enqueue(
        self,
        tpl: MailTemplate,
        recipients: list[str],
        *,
        context: dict[str, Any],
        lang: str | None,
        idempotency_parts: tuple[str, ...],
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
            html=rendered.html,
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


def _idem_parts(base: str | None, *parts: str) -> tuple[str, ...]:
    """Idempotenz-Bestandteile mit optionaler Basis (z. B. Flow-Action-Key)."""
    return (base, *parts) if base else parts


def _as_specs(raw: list[Any]) -> list[dict[str, Any]]:
    """Recipient-Rohdaten (JSONB-Liste) → Liste von Dicts (defensiv)."""
    return [r for r in raw if isinstance(r, dict)]


def _rule_out(rule: NotificationRule) -> NotificationRuleOut:
    return NotificationRuleOut(
        id=rule.id,
        event=rule.event,
        recipients=[RecipientSpec.model_validate(r) for r in rule.recipients],
        template_key=rule.template_key,
        application_type_id=rule.application_type_id,
        enabled=rule.enabled,
    )


def _template_out(tpl: MailTemplate) -> MailTemplateOut:
    return MailTemplateOut(
        id=tpl.id,
        key=tpl.key,
        subject_i18n=tpl.subject_i18n,
        body_i18n=tpl.body_i18n,
        body_html_i18n=tpl.body_html_i18n,
        placeholders=tpl.placeholders,
    )
