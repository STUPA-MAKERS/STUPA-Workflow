"""Aufgaben-Erinnerungen (#task-reminder, Kind ``task_reminder``).

Stündlicher Cron: findet Anträge, die seit ``task_reminder_after_days`` Tagen
unverändert in einem handlungsfähigen State stehen (mind. ein manueller
Übergang mit ``requires_action`` bzw. ``vote``-State), und erinnert alle, die
dort handeln können (Task-Semantik #64). Schwellen kommen aus der admin-
gepflegten Plattform-Config (``notification_settings``); ``repeat_days=0``
heißt: nur einmal je State-Aufenthalt.

``task_reminder_log`` (eine Zeile je Antrag, gebunden an das auslösende
``status_event``) verhindert Doppelversand — ein State-Wechsel startet den
Aufenthalt (und damit die Erinnerungs-Uhr) neu. Versand respektiert die
per-User-Abwahl (#4-2) und nutzt das Template ``task_reminder`` (DB-Override,
Builtin-Fallback).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.modules.applications.models import Application, StatusEvent
from app.modules.flow.models import State
from app.modules.notifications.models import TaskReminderLog
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
    """Auf naives UTC bringen. ``StatusEvent.at`` ist TIMESTAMP WITHOUT TIME ZONE —
    asyncpg lehnt einen tz-bewussten Bind dagegen ab (DataError) und
    ``now - entered_at`` wirft »can't subtract offset-naive and offset-aware«."""
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo is not None else dt


def _sessionmaker(ctx: dict[str, Any]) -> Any:
    """In Tests via ``ctx['sessionmaker']`` injizierbar (wie worker/deadlines)."""
    maker = ctx.get("sessionmaker")
    if maker is not None:
        return maker
    from app.db import get_sessionmaker

    return get_sessionmaker()


def _mail_queue(ctx: dict[str, Any]) -> Any:
    from app.modules.notifications.provider import mail_queue_from_pool

    return ctx.get("mail_queue") or mail_queue_from_pool(ctx.get("redis"))


async def process_task_reminders(
    ctx: dict[str, Any], *, now: datetime | None = None
) -> int:
    """Cron-Einstieg: fällige Erinnerungen versenden; gibt die Anzahl zurück."""
    now = now or datetime.now(UTC)
    settings: Settings = ctx.get("settings") or load_settings()
    maker = _sessionmaker(ctx)
    queue = _mail_queue(ctx)
    sent = 0
    async with maker() as session:
        service = NotificationService(session, queue=queue, settings=settings)
        config = await service.get_notification_settings()
        if not config.task_reminder_enabled:
            return 0
        due = await _due_applications(
            session,
            now=now,
            after=timedelta(days=config.task_reminder_after_days),
            repeat=timedelta(days=config.task_reminder_repeat_days)
            if config.task_reminder_repeat_days > 0
            else None,
        )
        for app_id, event_id, entered_at, state in due:
            try:
                if await _remind_one(
                    session,
                    service,
                    settings,
                    now=now,
                    application_id=app_id,
                    status_event_id=event_id,
                    entered_at=entered_at,
                    state=state,
                ):
                    sent += 1
            except Exception:  # noqa: BLE001 — Einzelfall darf den Zyklus nicht kippen
                logger.exception("task reminder failed (application=%s)", app_id)
    return sent


async def _due_applications(
    session: Any,
    *,
    now: datetime,
    after: timedelta,
    repeat: timedelta | None,
) -> list[tuple[uuid.UUID, uuid.UUID | None, datetime, State | None]]:
    """Fällige Anträge: (id, letztes status_event, Eintrittszeit, State).

    Fällig = bestätigter Antrag, State-Aufenthalt älter als ``after`` UND
    (noch nie für diesen Aufenthalt erinnert ODER letzte Erinnerung älter als
    ``repeat``; ``repeat=None`` = Einmal-Modus)."""
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

    states = {
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

    due: list[tuple[uuid.UUID, uuid.UUID | None, datetime, State | None]] = []
    for app_id, state_id, entered_at in rows:
        state = states.get(state_id)
        if state is None or not await state_actionable(session, state):
            continue
        event_id = await session.scalar(
            select(StatusEvent.id)
            .where(StatusEvent.application_id == app_id)
            .order_by(StatusEvent.at.desc())
            .limit(1)
        )
        log = logs.get(app_id)
        # Für diesen Aufenthalt bereits erinnert → nur im Wiederhol-Modus erneut.
        if (
            log is not None
            and log.status_event_id == event_id
            and (repeat is None or log.reminded_at > now - repeat)
        ):
            continue
        due.append((app_id, event_id, entered_at, state))
    return due


async def _remind_one(
    session: Any,
    service: NotificationService,
    settings: Settings,
    *,
    now: datetime,
    application_id: uuid.UUID,
    status_event_id: uuid.UUID | None,
    entered_at: datetime,
    state: State | None,
) -> bool:
    app_row = (
        await session.execute(
            select(Application.data, Application.gremium_id).where(
                Application.id == application_id
            )
        )
    ).first()
    if app_row is None:
        return False
    data, gremium_id = app_row
    recipients = await actionable_principal_emails(
        session, state=state, gremium_id=gremium_id
    )
    if not recipients:
        return False
    title = (data or {}).get("title")
    status_label = ""
    if state is not None and isinstance(state.label_i18n, dict) and state.label_i18n:
        status_label = state.label_i18n.get(settings.mail_default_lang) or next(
            iter(state.label_i18n.values())
        )
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
    )
    # Log auch ohne Versand (alle Empfänger abgewählt) setzen — sonst prüft jeder
    # Lauf dieselben Abgewählten erneut. ``sent`` zählt nur echte Mails.
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
