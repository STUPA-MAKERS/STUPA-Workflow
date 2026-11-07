"""Task reminders of the kind `task_reminder`.

An hourly cron finds the applications that stay unchanged for `task_reminder_after_days`
in an actionable state. An actionable state has at least one manual `requires_action`
transition, or it is a `vote` state. The cron reminds everyone who can act there. The
thresholds come from the admin-managed platform config `notification_settings`. A
`repeat_days` of 0 means one reminder per state stay.

`task_reminder_log` holds one row per application, bound to the `status_event` that
triggered the reminder. It prevents duplicate sends. A state change restarts the stay and
the reminder clock. A send respects the per-user opt-out. It uses the `task_reminder`
template, with the DB override first and the builtin as the fallback.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import Application, StatusEvent
from app.modules.flow.models import State
from app.modules.notifications.links import task_link
from app.modules.notifications.models import TaskReminderLog
from app.modules.notifications.provider import MailQueue
from app.modules.notifications.recipients import (
    actionable_principal_emails,
    state_actionable,
)
from app.modules.notifications.service import NotificationService
from app.modules.notifications.templates_catalogue import (
    TASK_REMINDER_BODY as _BUILTIN_REMINDER_BODY,
)
from app.modules.notifications.templates_catalogue import (
    TASK_REMINDER_SUBJECT as _BUILTIN_REMINDER_SUBJECT,
)
from app.settings import Settings, load_settings

logger = logging.getLogger("worker.task_reminders")


def _naive_utc(dt: datetime) -> datetime:
    """Convert a datetime to naive UTC.

    `StatusEvent.at` is TIMESTAMP WITHOUT TIME ZONE. asyncpg rejects a tz-aware bind, and
    `now - entered_at` would mix a naive value with an aware one.
    """
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo is not None else dt


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['sessionmaker']`)."""
    maker = ctx.get("sessionmaker")
    if maker is not None:
        return maker
    from app.db import get_sessionmaker

    return get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    from app.modules.notifications.provider import mail_queue_from_pool

    return ctx.get("mail_queue") or mail_queue_from_pool(ctx.get("redis"))


async def process_task_reminders(
    ctx: dict[str, Any], *, now: datetime | None = None
) -> int:
    """Send the due task reminders.

    This function is the arq cron entry point.

    Returns:
        The number of reminders sent.

    One failing case is logged and does not break the cycle.
    """
    moment = now or datetime.now(UTC)
    settings: Settings = ctx.get("settings") or load_settings()
    maker = _sessionmaker(ctx)
    queue = _mail_queue(ctx)
    async with maker() as session:
        service = NotificationService(session, queue=queue, settings=settings)
        config = await service.get_notification_settings()
        if not config.task_reminder_enabled:
            return 0
        due = await _due_applications(
            session,
            now=moment,
            after=timedelta(days=config.task_reminder_after_days),
            repeat=timedelta(days=config.task_reminder_repeat_days)
            if config.task_reminder_repeat_days > 0
            else None,
        )
        sent = [
            await _remind_one_logged(session, service, settings, moment, entry)
            for entry in due
        ]
    return sum(sent)


async def _remind_one_logged(
    session: AsyncSession,
    service: NotificationService,
    settings: Settings,
    now: datetime,
    entry: tuple[uuid.UUID, uuid.UUID | None, datetime, State | None],
) -> bool:
    """Send the reminder of one due entry; a failure logs and gives False.

    One failing case must not break the cycle, so the error stops here.
    """
    app_id, event_id, entered_at, state = entry
    try:
        return await _remind_one(
            session,
            service,
            settings,
            now=now,
            application_id=app_id,
            status_event_id=event_id,
            entered_at=entered_at,
            state=state,
        )
    except Exception:
        logger.exception("task reminder failed (application=%s)", app_id)
        return False


async def _due_applications(
    session: AsyncSession,
    *,
    now: datetime,
    after: timedelta,
    repeat: timedelta | None,
) -> list[tuple[uuid.UUID, uuid.UUID | None, datetime, State | None]]:
    """Return the due applications as (id, latest status_event, entered_at, state).

    An application is due when the applicant confirmed it and the state stay is older
    than `after`. The application must also have no reminder for this stay, or a last
    reminder older than `repeat`. A `repeat` of `None` means one reminder per stay.

    An application already reminded for this stay is sent again only in repeat mode.
    """
    latest_event = (
        select(
            StatusEvent.application_id.label("app_id"),
            func.max(StatusEvent.at).label("entered_at"),
        )
        .group_by(StatusEvent.application_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Application.id,
                Application.current_state_id,
                latest_event.c.entered_at,
            )
            .join(latest_event, latest_event.c.app_id == Application.id)
            .where(
                Application.current_state_id.is_not(None),
                Application.email_confirmed_at.is_not(None),
                latest_event.c.entered_at <= _naive_utc(now - after),
            )
        )
    ).all()
    if not rows:
        return []

    states: dict[uuid.UUID | None, State] = {
        s.id: s
        for s in (
            await session.scalars(
                select(State).where(
                    State.id.in_({r[1] for r in rows if r[1] is not None})
                )
            )
        ).all()
    }
    logs = {
        log.application_id: log
        for log in (
            await session.scalars(
                select(TaskReminderLog).where(
                    TaskReminderLog.application_id.in_({r[0] for r in rows})
                )
            )
        ).all()
    }

    entries = [
        await _due_entry(
            session,
            app_id,
            states.get(state_id),
            entered_at,
            logs.get(app_id),
            now=now,
            repeat=repeat,
        )
        for app_id, state_id, entered_at in rows
    ]
    return [entry for entry in entries if entry is not None]


async def _due_entry(
    session: AsyncSession,
    app_id: uuid.UUID,
    state: State | None,
    entered_at: datetime,
    log: TaskReminderLog | None,
    *,
    now: datetime,
    repeat: timedelta | None,
) -> tuple[uuid.UUID, uuid.UUID | None, datetime, State | None] | None:
    """Return the due entry of one application, or `None` when it is not due.

    It is not due when nobody can act on its state, or when the log already holds a
    reminder for this stay that `_reminded` still counts.
    """
    if state is None or not await state_actionable(session, state):
        return None
    event_id = await session.scalar(
        select(StatusEvent.id)
        .where(StatusEvent.application_id == app_id)
        .order_by(StatusEvent.at.desc())
        .limit(1)
    )
    return (
        None
        if _reminded(log, event_id, now=now, repeat=repeat)
        else (app_id, event_id, entered_at, state)
    )


def _reminded(
    log: TaskReminderLog | None,
    event_id: uuid.UUID | None,
    *,
    now: datetime,
    repeat: timedelta | None,
) -> bool:
    """Tell whether the log holds a reminder for this stay that still counts.

    Without `repeat` one reminder per stay counts forever; with it, only one newer than
    `repeat`.
    """
    return (
        log is not None
        and log.status_event_id == event_id
        and (repeat is None or log.reminded_at > now - repeat)
    )


def _status_label(state: State | None, lang: str) -> str:
    """Return the label of the state in `lang`, else its first label, else an empty string."""
    labels = state.label_i18n if state is not None else None
    return (
        labels.get(lang) or next(iter(labels.values()))
        if isinstance(labels, dict) and labels
        else ""
    )


async def _remind_one(
    session: AsyncSession,
    service: NotificationService,
    settings: Settings,
    *,
    now: datetime,
    application_id: uuid.UUID,
    status_event_id: uuid.UUID | None,
    entered_at: datetime,
    state: State | None,
) -> bool:
    """Send one task reminder and write its log; return whether a mail went out.

    The log is written even without a send, for example when all recipients opted out,
    because without it every run re-checks the same opted-out set.
    """
    app_row = (
        await session.execute(
            select(Application.data).where(Application.id == application_id)
        )
    ).first()
    if app_row is None:
        return False
    (data,) = app_row
    recipients = await actionable_principal_emails(
        session, application_id=application_id, state=state
    )
    if not recipients:
        return False
    title = (data or {}).get("title")
    status_label = _status_label(state, settings.mail_default_lang)
    sent = await service.send_kind_mail(
        recipients,
        kind="task_reminder",
        template_key="task_reminder",
        builtin_subject=_BUILTIN_REMINDER_SUBJECT,
        builtin_body=_BUILTIN_REMINDER_BODY,
        context={
            "applicationId": str(application_id),
            "applicationTitle": title.strip() if isinstance(title, str) else "",
            "status": status_label,
            "daysOpen": max(1, (_naive_utc(now) - _naive_utc(entered_at)).days),
        },
        idempotency_parts=(
            "task_reminder",
            str(application_id),
            str(status_event_id or ""),
            now.date().isoformat(),
        ),
        link=task_link(settings, application_id),
    )
    log = await session.get(TaskReminderLog, application_id)
    if log is None:
        session.add(
            TaskReminderLog(
                application_id=application_id,
                status_event_id=status_event_id,
                reminded_at=now,
            )
        )
    else:
        log.status_event_id = status_event_id
        log.reminded_at = now
    await session.commit()
    return bool(sent)
