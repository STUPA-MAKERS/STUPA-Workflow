"""arq-Cron-Task: zeitgesteuerte Frist-/Vote-Verarbeitung (T-44, flows §9.4, R12).

``process_deadlines`` läuft periodisch (minütlich, ``worker.main``) und erledigt drei
idempotente Schritte gegen einen **zeitzonenbewussten** ``now`` (UTC):

1. **Erinnerungen** — Fristen im Lead-Fenster (``due_at-lead <= now < due_at``), die noch
   nicht erinnert wurden → ``notify(deadline_approaching)`` + ``reminded_at`` setzen
   (genau einmal).
2. **Auto-Übergänge / Wiedervorlage** — abgelaufene Fristen mit ``action_on_pass`` →
   ``flow.fire`` (Guard ``deadlinePassed``, ``manual=False``); danach ``action_on_pass``
   leeren (Idempotenz-Marker). ``kind="requeue"`` ist der Wiedervorlage-Fall: der Antrag
   geht über den referenzierten Übergang aus »vertagt« zurück (Historie = ``status_event``).
3. **Vote-Auto-Close** — offene Votes mit abgelaufenem ``closes_at`` → ``voting.close``
   (zählt aus, feuert den Ergebnis-Branch).

**Nebenläufigkeit.** Jede Einheit wird in eigener Session via ``FOR UPDATE SKIP LOCKED``
gesperrt (``DeadlineService.lock_*``): ein zweiter Worker sieht die gesperrte Zeile nicht
und überspringt → keine Doppelausführung (Akzeptanzkriterium). Zusätzlich sind die
fachlichen Operationen selbst idempotent (optimistisches Locking in ``flow.fire``;
Status-Check in ``voting.close``; ``_job_id``-Dedup beim Mail-Enqueue).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.deadlines.service import DeadlineService, transition_ref
from app.modules.flow.models import Transition
from app.modules.flow.service import FlowService
from app.modules.notifications.action_dispatcher import build_notify_dispatcher
from app.modules.notifications.queue import ArqMailQueue, MailQueue
from app.modules.notifications.service import NotificationService
from app.modules.voting.service import VotingService
from app.settings import Settings, load_settings
from app.shared.errors import ConflictError, NotFoundError

logger = logging.getLogger("app.deadlines")

# Gast-Anträge ohne E-Mail-Bestätigung werden nach diesem Fenster verworfen (#confirm).
_GUEST_CONFIRM_TTL = timedelta(hours=12)


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["settings"] = load_settings()


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """DB-Sessionmaker (in Tests via ``ctx['deadlines_sessionmaker']`` injizierbar)."""
    maker = ctx.get("deadlines_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _now() -> datetime:
    """Zeitzonenbewusster Jetzt-Zeitpunkt (UTC) — freezegun-steuerbar in Tests."""
    return datetime.now(UTC)


def _system_principal() -> Principal:
    """Akteur für cron-getriggerte Übergänge (kein User). Guards der Auto-Übergänge
    sind ``deadlinePassed``/``voteResult`` (kein RBAC); ``application.manage`` deckt
    etwaige Rollen-Guards der Requeue-/Ergebnis-Branches ab."""
    return Principal(
        sub="system:deadlines",
        roles=["system"],
        permissions={"application.manage"},
    )


def _mail_queue(ctx: dict[str, Any]) -> MailQueue | None:
    """Mail-Queue aus dem arq-Redis-Pool (oder Test-Injektion). ``None`` ohne Redis."""
    queue = ctx.get("mail_queue")
    if queue is not None:
        return queue  # type: ignore[return-value]
    pool = ctx.get("redis")
    return ArqMailQueue(pool) if pool is not None else None


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
async def process_deadlines(ctx: dict[str, Any]) -> str:
    """Erinnerungen + Auto-Übergänge + Vote-Auto-Close (idempotent, SKIP LOCKED)."""
    settings: Settings = ctx.get("settings") or load_settings()
    now = _now()
    reminded = await _process_reminders(ctx, settings, now)
    fired = await _process_actions(ctx, settings, now)
    closed = await _process_votes(ctx, now)
    advanced = await _process_auto_transitions(ctx)
    discarded = await _discard_unconfirmed(ctx, now)
    return (
        f"reminders={reminded} actions={fired} votes={closed} "
        f"auto={advanced} discarded={discarded}"
    )


# --------------------------------------------------------------------------- #
# 4. Verwurf unbestätigter Gast-Anträge (#confirm)
# --------------------------------------------------------------------------- #
async def _discard_unconfirmed(ctx: dict[str, Any], now: datetime) -> int:
    """Gast-Anträge ohne E-Mail-Bestätigung nach 12 h hart löschen.

    Nur anonyme (``created_by IS NULL``) **und** unbestätigte
    (``email_confirmed_at IS NULL``) Anträge älter als das TTL-Fenster. FK-Abhängige
    (Applicant/Versionen/Status-Events/Dateien …) kaskadieren; idempotent (ein zweiter
    Lauf findet nichts mehr)."""
    maker = _sessionmaker(ctx)
    cutoff = now - _GUEST_CONFIRM_TTL
    async with maker() as session:
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                delete(Application).where(
                    Application.created_by.is_(None),
                    Application.email_confirmed_at.is_(None),
                    Application.created_at < cutoff,
                )
            ),
        )
        await session.commit()
    discarded = result.rowcount or 0
    if discarded:
        logger.info("discarded %d unconfirmed guest application(s)", discarded)
    return discarded


# --------------------------------------------------------------------------- #
# 1. Reminders
# --------------------------------------------------------------------------- #
async def _process_reminders(
    ctx: dict[str, Any], settings: Settings, now: datetime
) -> int:
    maker = _sessionmaker(ctx)
    lead = timedelta(minutes=settings.deadline_reminder_lead_minutes)
    async with maker() as session:
        ids = await DeadlineService(session).due_reminder_ids(now, lead)
    sent = 0
    for deadline_id in ids:
        try:
            if await _remind_one(ctx, settings, deadline_id, now, lead):
                sent += 1
        except Exception:  # noqa: BLE001 — kaputte Einzel-Frist darf den Zyklus nicht abbrechen
            logger.exception("deadline reminder failed (deadline=%s)", deadline_id)
    return sent


async def _remind_one(
    ctx: dict[str, Any],
    settings: Settings,
    deadline_id: UUID,
    now: datetime,
    lead: timedelta,
) -> bool:
    maker = _sessionmaker(ctx)
    queue = _mail_queue(ctx)
    async with maker() as session:
        svc = DeadlineService(session)
        deadline = await svc.lock_reminder(deadline_id, now, lead)
        if deadline is None:
            return False  # anderer Worker / nicht mehr fällig
        type_id = deadline.type_id
        if type_id is None and deadline.application_id is not None:
            type_id = await session.scalar(
                select(Application.type_id).where(
                    Application.id == deadline.application_id
                )
            )
        notifier = NotificationService(session, queue=queue, settings=settings)
        await notifier.handle_notify_action(
            {"templateKey": "deadline_approaching", "recipients": [{"kind": "applicant"}]},
            application_id=deadline.application_id,
            application_type_id=type_id,
            context={
                "deadlineId": str(deadline.id),
                "kind": deadline.kind,
                "dueAt": deadline.due_at.isoformat(),
            },
            lang=None,
            idempotency_base=f"deadline:{deadline.id}",
        )
        await svc.mark_reminded(deadline, now)
    logger.info("deadline reminder sent (deadline=%s kind=%s)", deadline_id, deadline.kind)
    return True


# --------------------------------------------------------------------------- #
# 2. Auto-transitions / requeue
# --------------------------------------------------------------------------- #
async def _process_actions(
    ctx: dict[str, Any], settings: Settings, now: datetime
) -> int:
    maker = _sessionmaker(ctx)
    async with maker() as session:
        ids = await DeadlineService(session).due_action_deadline_ids(now)
    fired = 0
    for deadline_id in ids:
        try:
            if await _fire_one(ctx, deadline_id, now):
                fired += 1
        except Exception:  # noqa: BLE001 — kaputte Einzel-Frist darf den Zyklus nicht abbrechen
            logger.exception("deadline action failed (deadline=%s)", deadline_id)
    return fired


async def _fire_one(ctx: dict[str, Any], deadline_id: UUID, now: datetime) -> bool:
    maker = _sessionmaker(ctx)
    dispatcher = ctx.get("flow_dispatcher") or build_notify_dispatcher(ctx.get("redis"))
    async with maker() as session:
        svc = DeadlineService(session)
        deadline = await svc.lock_action_deadline(deadline_id, now)
        if deadline is None:
            return False  # anderer Worker / bereits konsumiert
        application_id = deadline.application_id
        transition_id = transition_ref(deadline.action_on_pass)
        if application_id is None or transition_id is None:
            logger.warning(
                "deadline %s has action_on_pass without application/transition — skipped",
                deadline_id,
            )
            await svc.consume_action(deadline)  # nicht erneut scannen
            return False
        flow = FlowService(session, dispatcher)
        fired = False
        # Marker VOR dem Feuern vormerken: `fire` committet ihn atomar mit dem
        # State-Wechsel — kein Fenster, in dem ein zweiter Worker die schon
        # gefeuerte Frist erneut greifen kann (das Row-Lock fällt mit dem Commit).
        deadline.action_on_pass = None
        try:
            await flow.fire(
                application_id,
                transition_id,
                _system_principal(),
                note=f"deadline:{deadline.kind}",
                deadline_passed=True,
                manual=False,
            )
            fired = True
        except ConflictError as exc:
            # Guard nicht erfüllt oder Zustand bereits gewechselt (konkurrierende
            # Transition) — die Frist ist verbraucht, nicht erneut feuern.
            logger.info("deadline %s transition not applied: %s", deadline_id, exc)
        except NotFoundError as exc:
            logger.warning("deadline %s references missing app/transition: %s", deadline_id, exc)
        # Fehlerpfade (kein Commit durch `fire` bzw. Rollback) — Marker hier
        # persistieren; nach erfolgreichem `fire` ist das ein No-op.
        await svc.consume_action(deadline)
    return fired


# --------------------------------------------------------------------------- #
# 2b. Automatische Übergänge (#8)
# --------------------------------------------------------------------------- #
async def _process_auto_transitions(ctx: dict[str, Any]) -> int:
    """Konfigurierte **automatische** Übergänge feuern, deren Guard erfüllt ist (#8).

    Scannt Anträge, deren aktueller State eine ausgehende ``automatic``-Transition
    besitzt, und feuert (``manual=False``) den ersten passenden. Idempotent über das
    optimistische Locking in ``flow.fire``; je Antrag eigene Session.
    """
    maker = _sessionmaker(ctx)
    dispatcher = ctx.get("flow_dispatcher") or build_notify_dispatcher(ctx.get("redis"))
    async with maker() as session:
        auto_states = select(Transition.from_state_id).where(Transition.automatic)
        ids = list(
            (
                await session.execute(
                    select(Application.id).where(
                        Application.current_state_id.is_not(None),
                        Application.current_state_id.in_(auto_states),
                    )
                )
            )
            .scalars()
            .all()
        )
    advanced = 0
    for application_id in ids:
        try:
            async with maker() as session:
                flow = FlowService(session, dispatcher)
                if await flow.auto_advance(application_id, _system_principal()) is not None:
                    advanced += 1
        except (ConflictError, NotFoundError) as exc:
            logger.info("auto-transition skipped (app=%s): %s", application_id, exc)
        except Exception:  # noqa: BLE001 — ein kaputter Antrag darf den Zyklus nicht abbrechen
            logger.exception("auto-transition failed (app=%s)", application_id)
    return advanced


# --------------------------------------------------------------------------- #
# 3. Vote auto-close
# --------------------------------------------------------------------------- #
async def _process_votes(ctx: dict[str, Any], now: datetime) -> int:
    maker = _sessionmaker(ctx)
    async with maker() as session:
        ids = await DeadlineService(session).due_open_vote_ids(now)
    closed = 0
    for vote_id in ids:
        try:
            if await _close_one(ctx, vote_id, now):
                closed += 1
        except Exception:  # noqa: BLE001 — kaputter Einzel-Vote darf den Zyklus nicht abbrechen
            logger.exception("vote auto-close failed (vote=%s)", vote_id)
    return closed


async def _close_one(ctx: dict[str, Any], vote_id: UUID, now: datetime) -> bool:
    maker = _sessionmaker(ctx)
    dispatcher = ctx.get("flow_dispatcher") or build_notify_dispatcher(ctx.get("redis"))
    async with maker() as session:
        svc = DeadlineService(session)
        vote = await svc.lock_open_vote(vote_id, now)
        if vote is None:
            return False  # anderer Worker / bereits geschlossen
        voting = VotingService(session, dispatcher)
        try:
            # ``now`` mitgeben, damit ein zeit-gebundener Vote mit abgelaufenem
            # Fenster und unerfülltem Quorum terminal (fail-Branch) schließt statt
            # ewig vom Cron erneut gegriffen zu werden (#stuck-vote).
            await voting.close(vote.id, _system_principal(), now=now)
        except ConflictError as exc:
            logger.info("vote %s auto-close skipped: %s", vote_id, exc)
            return False
        except NotFoundError as exc:
            logger.warning("vote %s auto-close — app missing: %s", vote_id, exc)
            return False
    logger.info("vote auto-closed (vote=%s)", vote_id)
    return True
