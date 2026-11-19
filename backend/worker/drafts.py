"""Draft reminders of the kind ``draft_reminder`` (spec 001711).

An hourly cron finds the drafts that had no change for `DRAFT_REMINDER_AFTER`: a
confirmed, not archived Antrag in the initial state of its flow whose ``updated_at`` is
older than that. It sends the mail ``draft_reminder`` to the applicant, with the DB
template first and the builtin as the fallback, and sets ``draft_reminder_at``. The
column is set also when no mail goes out (an opt-out or an anonymized applicant),
because each draft gets at most one reminder and the next run must not check it again.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.mail_data import application_specs, resolve_application_lang
from app.modules.applications.models import Application
from app.modules.flow.models import State
from app.modules.notifications.links import application_link
from app.modules.notifications.provider import MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.notifications.texts.drafts import (
    DRAFT_REMINDER_BODY,
    DRAFT_REMINDER_KEY,
    DRAFT_REMINDER_SUBJECT,
)
from app.settings import Settings, load_settings

logger = logging.getLogger("worker.drafts")

#: A draft without a change for this long gets its one reminder.
DRAFT_REMINDER_AFTER = timedelta(days=7)


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via ``ctx['sessionmaker']``)."""
    maker = ctx.get("sessionmaker")
    if maker is not None:
        return maker
    from app.db import get_sessionmaker

    return get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    from app.modules.notifications.provider import mail_queue_from_pool

    return ctx.get("mail_queue") or mail_queue_from_pool(ctx.get("redis"))


async def due_drafts(session: AsyncSession, *, now: datetime) -> list[Application]:
    """Return the drafts that are due for their reminder, oldest change first."""
    return list(
        (
            await session.scalars(
                select(Application)
                .join(State, State.id == Application.current_state_id)
                .where(
                    State.is_initial.is_(True),
                    Application.email_confirmed_at.is_not(None),
                    Application.archived_at.is_(None),
                    Application.draft_reminder_at.is_(None),
                    Application.updated_at <= now - DRAFT_REMINDER_AFTER,
                )
                .order_by(Application.updated_at)
            )
        ).all()
    )


async def process_draft_reminders(ctx: dict[str, Any], *, now: datetime | None = None) -> int:
    """Send the due draft reminders.

    This function is the arq cron entry point. One failing draft is logged and does
    not break the cycle.

    Returns:
        The number of reminders sent.
    """
    moment = now or datetime.now(UTC)
    settings: Settings = ctx.get("settings") or load_settings()
    queue = _mail_queue(ctx)
    async with _sessionmaker(ctx)() as session:
        service = NotificationService(
            session, queue=queue, settings=settings, expand_specs=application_specs
        )
        drafts = [
            (app.id, app.data, app.created_by, app.updated_at)
            for app in await due_drafts(session, now=moment)
        ]
        sent = [await _remind_logged(session, service, settings, moment, draft) for draft in drafts]
    return sum(sent)


async def _remind_logged(
    session: AsyncSession,
    service: NotificationService,
    settings: Settings,
    now: datetime,
    draft: tuple[uuid.UUID, dict[str, Any] | None, str | None, datetime],
) -> bool:
    """Send the reminder of one draft; a failure logs, rolls back and gives False."""
    try:
        return await _remind(session, service, settings, now, draft)
    except Exception:
        await session.rollback()
        logger.exception("draft reminder failed (application=%s)", draft[0])
        return False


async def _remind(
    session: AsyncSession,
    service: NotificationService,
    settings: Settings,
    now: datetime,
    draft: tuple[uuid.UUID, dict[str, Any] | None, str | None, datetime],
) -> bool:
    """Send the reminder of one draft and mark the draft; return whether a mail went out."""
    application_id, data, created_by, changed_at = draft
    title = (data or {}).get("title")
    recipients = await service.resolver.resolve(
        [{"kind": "applicant"}], application_id=application_id
    )
    lang = await resolve_application_lang(session, application_id=application_id, settings=settings)
    sent = bool(recipients) and await service.send_kind_mail(
        recipients,
        kind=DRAFT_REMINDER_KEY,
        template_key=DRAFT_REMINDER_KEY,
        builtin_subject=DRAFT_REMINDER_SUBJECT,
        builtin_body=DRAFT_REMINDER_BODY,
        context={
            "applicationId": str(application_id),
            "applicationTitle": title.strip() if isinstance(title, str) else "",
            "daysIdle": max(1, (now - changed_at).days),
        },
        idempotency_parts=(DRAFT_REMINDER_KEY, str(application_id)),
        lang=lang,
        link=application_link(settings, application_id, guest=created_by is None),
    )
    await session.execute(
        update(Application)
        .where(Application.id == application_id)
        .values(draft_reminder_at=now, updated_at=Application.updated_at)
    )
    await session.commit()
    return sent
