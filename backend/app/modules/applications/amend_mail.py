"""The mail to the applicant about a changed approved amount (spec 001621).

The mail names the old and the new amount and the Gremium and the date of the decision
that allows the change. It never names the person who changed the amount and never the
reason, because the reason is an internal note. The applicant gets the mail in the
language of the application. The opt-out of the kind `status_update` applies, because
the mail reports on the own application. The template `approved_amount_changed` has a
builtin fallback. The route runs this as a background task with its own session.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.mail_data import application_specs, resolve_application_lang
from app.modules.applications.models import Application
from app.modules.gremien.models import Gremium
from app.modules.notifications.links import application_link
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.service import NotificationService, filter_recipients_by_preference
from app.modules.notifications.templating import TemplateRenderError, render_mail
from app.modules.notifications.texts.decisions import (
    AMOUNT_CHANGED_BODY,
    AMOUNT_CHANGED_KEY,
    AMOUNT_CHANGED_KIND,
    AMOUNT_CHANGED_SUBJECT,
)
from app.settings import Settings
from app.shared.money import format_money

logger = logging.getLogger("app.notifications")


def _date_text(value: date, lang: str) -> str:
    """Return a date as the reader writes it: 19.11.2026 or 2026-11-19."""
    return value.strftime("%d.%m.%Y") if lang == "de" else value.isoformat()


@dataclass(frozen=True, slots=True)
class MailFacts:
    """The rows that the mail reads: the answers, the currency, the creator, the Gremium."""

    data: dict[str, Any] | None
    currency: str | None
    created_by: str | None
    gremium: str | None


async def mail_facts(
    session: AsyncSession, application_id: uuid.UUID, gremium_id: uuid.UUID
) -> MailFacts | None:
    """Read the facts of the mail, or None for an application that does not exist."""
    row = (
        await session.execute(
            select(Application.data, Application.currency, Application.created_by).where(
                Application.id == application_id
            )
        )
    ).first()
    if row is None:
        return None
    gremium = await session.scalar(select(Gremium.name).where(Gremium.id == gremium_id))
    return MailFacts(data=row[0], currency=row[1], created_by=row[2], gremium=gremium)


async def send_amount_changed_mail(
    session: AsyncSession,
    *,
    queue: MailQueue | None,
    settings: Settings,
    application_id: uuid.UUID,
    previous: Decimal | None,
    approved: Decimal,
    gremium_id: uuid.UUID,
    decision_date: date,
) -> int:
    """Send the mail about the changed approved amount to the applicant.

    Returns:
        The number of mail jobs that went to the queue.
    """
    facts = await mail_facts(session, application_id, gremium_id)
    if facts is None:
        return 0
    service = NotificationService(
        session, queue=queue, settings=settings, expand_specs=application_specs
    )
    lang = await resolve_application_lang(session, application_id=application_id, settings=settings)
    title = (facts.data or {}).get("title")
    cur = facts.currency or "EUR"
    link = application_link(settings, application_id, guest=facts.created_by is None)
    context: dict[str, object] = {
        "link": link.url,
        "applicationId": str(application_id),
        "applicationTitle": title.strip() if isinstance(title, str) else "",
        "previousAmount": "" if previous is None else format_money(previous, cur, lang),
        "approvedAmount": format_money(approved, cur, lang),
        "gremium": facts.gremium or "",
        "decisionDate": _date_text(decision_date, lang),
    }
    resolved = await service.resolver.resolve(
        [{"kind": "applicant"}], application_id=application_id
    )
    recipients = await filter_recipients_by_preference(session, resolved, AMOUNT_CHANGED_KIND)
    if not recipients:
        return 0
    idem = ("amount_changed", str(application_id), str(approved), decision_date.isoformat())
    tpl = await service._get_template_by_key(AMOUNT_CHANGED_KEY)
    if tpl is not None:
        ok = await service._render_and_enqueue(
            tpl,
            recipients,
            context=context,
            lang=lang,
            idempotency_parts=idem,
            reason=AMOUNT_CHANGED_KIND,
            link=link,
        )
        return int(ok)
    try:
        rendered = render_mail(
            subject_i18n=AMOUNT_CHANGED_SUBJECT,
            body_i18n=AMOUNT_CHANGED_BODY,
            context=await service.render_context(context),
            lang=lang,
            default_lang=settings.mail_default_lang,
        )
    except TemplateRenderError as exc:
        logger.warning("amount-changed builtin render failed: %s", exc)
        return 0
    msg = await service._message(rendered, recipients, AMOUNT_CHANGED_KIND, idem, link)
    return int(await service._enqueue(msg))
