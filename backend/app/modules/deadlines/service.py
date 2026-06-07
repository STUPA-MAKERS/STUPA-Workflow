"""Deadline-Service (T-44, flows §9.4): Scan + Lock + Idempotenz-Marker.

Reine DB-Schicht für den arq-Cron (:mod:`worker.deadlines`). Die fachliche Wirkung
(Übergang feuern, Vote schließen, Erinnerung versenden) liegt im Worker; dieser
Service liefert die **fälligen** Datensätze und setzt die Marker.

**Nebenläufigkeit (mehrere Worker).** Die ``lock_*``-Methoden selektieren eine **einzelne**
Zeile mit ``FOR UPDATE SKIP LOCKED``: greift ein zweiter Worker dieselbe Frist ab, sieht
er sie nicht (``None``) und überspringt — keine Doppelausführung (flows §9.4, Risiko-Note).
Der Persistenz-Marker (``action_on_pass=NULL`` bzw. ``reminded_at``) verhindert die
Wiederholung über Worker-Neustarts hinweg.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deadlines.models import Deadline
from app.modules.voting.models import Vote


class DeadlineService:
    """An eine ``AsyncSession`` gebundene Frist-Operationen."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ create
    async def create(
        self,
        *,
        kind: str,
        due_at: datetime,
        application_id: UUID | None = None,
        type_id: UUID | None = None,
        action_on_pass: dict | None = None,
    ) -> Deadline:
        """Frist anlegen/speichern (programmatische API — kein HTTP-Endpunkt, api.md)."""
        deadline = Deadline(
            kind=kind,
            due_at=due_at,
            application_id=application_id,
            type_id=type_id,
            action_on_pass=action_on_pass,
        )
        self.session.add(deadline)
        await self.session.flush()
        await self.session.commit()
        return deadline

    # ------------------------------------------------------------------- scans
    async def due_action_deadline_ids(self, now: datetime) -> list[UUID]:
        """IDs fälliger Auto-Fristen (``due_at<=now`` ∧ ``action_on_pass`` gesetzt)."""
        rows = (
            await self.session.execute(
                select(Deadline.id).where(
                    Deadline.action_on_pass.isnot(None),
                    Deadline.due_at <= now,
                )
            )
        ).scalars().all()
        return list(rows)

    async def due_reminder_ids(self, now: datetime, lead: timedelta) -> list[UUID]:
        """IDs anstehender Fristen im Erinnerungsfenster (``due_at-lead <= now < due_at``),
        die noch nicht erinnert wurden."""
        rows = (
            await self.session.execute(
                select(Deadline.id).where(
                    Deadline.reminded_at.is_(None),
                    Deadline.due_at > now,
                    Deadline.due_at <= now + lead,
                )
            )
        ).scalars().all()
        return list(rows)

    async def due_open_vote_ids(self, now: datetime) -> list[UUID]:
        """IDs offener Votes mit abgelaufenem Fenster (``closes_at<=now``)."""
        rows = (
            await self.session.execute(
                select(Vote.id).where(
                    Vote.status == "open",
                    Vote.closes_at.isnot(None),
                    Vote.closes_at <= now,
                )
            )
        ).scalars().all()
        return list(rows)

    # ------------------------------------------------------------------- locks
    async def lock_action_deadline(
        self, deadline_id: UUID, now: datetime
    ) -> Deadline | None:
        """Fällige Auto-Frist exklusiv sperren (``SKIP LOCKED``) — ``None``, wenn von
        einem anderen Worker gehalten oder zwischenzeitlich konsumiert."""
        return (
            await self.session.execute(
                select(Deadline)
                .where(
                    Deadline.id == deadline_id,
                    Deadline.action_on_pass.isnot(None),
                    Deadline.due_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

    async def lock_reminder(
        self, deadline_id: UUID, now: datetime, lead: timedelta
    ) -> Deadline | None:
        """Anstehende, noch nicht erinnerte Frist exklusiv sperren (``SKIP LOCKED``)."""
        return (
            await self.session.execute(
                select(Deadline)
                .where(
                    Deadline.id == deadline_id,
                    Deadline.reminded_at.is_(None),
                    Deadline.due_at > now,
                    Deadline.due_at <= now + lead,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

    async def lock_open_vote(self, vote_id: UUID, now: datetime) -> Vote | None:
        """Offenen, abgelaufenen Vote exklusiv sperren (``SKIP LOCKED``)."""
        return (
            await self.session.execute(
                select(Vote)
                .where(
                    Vote.id == vote_id,
                    Vote.status == "open",
                    Vote.closes_at.isnot(None),
                    Vote.closes_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()

    # ----------------------------------------------------------------- markers
    async def consume_action(self, deadline: Deadline) -> None:
        """Auto-Frist als gefeuert markieren (``action_on_pass=NULL``) + committen.

        Entfernt die Zeile aus dem partiellen Scan-Index → kein erneutes Feuern."""
        deadline.action_on_pass = None
        await self.session.commit()

    async def mark_reminded(self, deadline: Deadline, now: datetime) -> None:
        """Erinnerung als versandt markieren (``reminded_at=now``) + committen."""
        deadline.reminded_at = now
        await self.session.commit()


def transition_ref(action_on_pass: dict | None) -> UUID | None:
    """Transition-UUID aus ``action_on_pass`` lesen (``{"transitionId": "<uuid>"}``).

    Defensiv: fehlender/ungültiger Wert → ``None`` (Aufrufer überspringt die Frist)."""
    if not action_on_pass:
        return None
    raw = action_on_pass.get("transitionId") or action_on_pass.get("transition_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None
