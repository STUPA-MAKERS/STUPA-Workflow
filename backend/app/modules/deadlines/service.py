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

from app.modules.deadlines.models import Deadline, DeadlinePolicy
from app.modules.voting.models import Vote

# Obergrenze je Cron-Tick (AUD-046): jeder Scan liefert höchstens so viele, **älteste
# zuerst** (``due_at``/``closes_at`` aufsteigend). So drainiert ein großer Rückstau (z. B.
# nach Downtime oder einem geteilten absolute-Policy-Rollover über tausende Anträge) über
# mehrere Ticks, statt dass ein einzelner Tick die gesamte Kohorte sequenziell abarbeitet
# und über die 1-Minuten-Kadenz hinaus läuft. Korrektheit unberührt (SKIP LOCKED +
# Idempotenz-Marker): nicht gegriffene Zeilen bleiben fällig und kommen im nächsten Tick.
DEFAULT_SCAN_LIMIT = 200


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
    async def due_action_deadline_ids(
        self, now: datetime, *, limit: int = DEFAULT_SCAN_LIMIT
    ) -> list[UUID]:
        """IDs fälliger Auto-Fristen (``due_at<=now`` ∧ ``action_on_pass`` gesetzt).

        Pro Tick auf ``limit`` (älteste ``due_at`` zuerst) begrenzt → großer Rückstau
        drainiert über mehrere Ticks (AUD-046)."""
        rows = (
            await self.session.execute(
                select(Deadline.id)
                .where(
                    Deadline.action_on_pass.isnot(None),
                    Deadline.due_at <= now,
                )
                .order_by(Deadline.due_at)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def due_reminder_ids(
        self, now: datetime, lead: timedelta, *, limit: int = DEFAULT_SCAN_LIMIT
    ) -> list[UUID]:
        """IDs anstehender (oder bereits abgelaufener) Fristen, die noch nicht erinnert
        wurden (``reminded_at IS NULL`` ∧ ``due_at <= now+lead``).

        **Keine untere Schranke** (``due_at > now``): War der Worker länger als das
        Lead-Fenster aus oder wurde die Frist bereits-überfällig angelegt, würde eine
        zweiseitige Bedingung die Zeile nie mehr greifen → die Erinnerung bliebe für
        immer aus und die Zeile leckte im partiellen Index ``ix_deadline_reminder``
        (AUD-037). So wird genau einmal eine (ggf. verspätete) Erinnerung versandt und
        ``reminded_at`` gesetzt → die Zeile verlässt den Scan-Index.

        Pro Tick auf ``limit`` (älteste ``due_at`` zuerst) begrenzt (AUD-046)."""
        rows = (
            await self.session.execute(
                select(Deadline.id)
                .where(
                    Deadline.reminded_at.is_(None),
                    Deadline.due_at <= now + lead,
                )
                .order_by(Deadline.due_at)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def due_open_vote_ids(
        self, now: datetime, *, limit: int = DEFAULT_SCAN_LIMIT
    ) -> list[UUID]:
        """IDs offener Votes mit abgelaufenem Fenster (``closes_at<=now``).

        Pro Tick auf ``limit`` (ältestes ``closes_at`` zuerst) begrenzt (AUD-046)."""
        rows = (
            await self.session.execute(
                select(Vote.id)
                .where(
                    Vote.status == "open",
                    Vote.closes_at.isnot(None),
                    Vote.closes_at <= now,
                )
                .order_by(Vote.closes_at)
                .limit(limit)
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
        """Anstehende (oder bereits abgelaufene), noch nicht erinnerte Frist exklusiv
        sperren (``SKIP LOCKED``). Spiegelt :meth:`due_reminder_ids`: keine untere
        Schranke, damit verspätete Erinnerungen genau einmal versandt werden (AUD-037)."""
        return (
            await self.session.execute(
                select(Deadline)
                .where(
                    Deadline.id == deadline_id,
                    Deadline.reminded_at.is_(None),
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


def resolve_due_at(
    policy: DeadlinePolicy,
    *,
    submitted_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> datetime | None:
    """Konkrete Frist aus einer Policy + Antrags-Zeitpunkten ableiten (pure).

    ``absolute`` → das hinterlegte Datum; ``relative_submitted`` → Einreichung +
    ``offset_days``; ``relative_changed`` → letzte Änderung + ``offset_days``.
    Fehlt der nötige Bezugswert (z. B. kein ``submitted_at``), → ``None``."""
    if policy.kind == "absolute":
        return policy.absolute_at
    days = policy.offset_days or 0
    if policy.kind == "relative_submitted":
        return submitted_at + timedelta(days=days) if submitted_at else None
    if policy.kind == "relative_changed":
        return changed_at + timedelta(days=days) if changed_at else None
    return None


class DeadlinePolicyError(Exception):
    """Verletzte Policy-Invariante (z. B. doppelter Key) → 409/422 im Router."""


class DeadlinePolicyService:
    """CRUD der benannten Frist-Policies (Registry, admin-gepflegt)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[DeadlinePolicy]:
        rows = (
            await self.session.execute(
                select(DeadlinePolicy).order_by(DeadlinePolicy.key)
            )
        ).scalars().all()
        return list(rows)

    async def get(self, policy_id: UUID) -> DeadlinePolicy | None:
        return await self.session.get(DeadlinePolicy, policy_id)

    async def get_by_key(self, key: str) -> DeadlinePolicy | None:
        return (
            await self.session.execute(
                select(DeadlinePolicy).where(DeadlinePolicy.key == key)
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        key: str,
        label: dict,
        kind: str,
        absolute_at: datetime | None,
        offset_days: int | None,
    ) -> DeadlinePolicy:
        if await self.get_by_key(key):
            raise DeadlinePolicyError(f"deadline policy key already exists: {key!r}")
        policy = DeadlinePolicy(
            key=key,
            label=label,
            kind=kind,
            absolute_at=absolute_at if kind == "absolute" else None,
            offset_days=offset_days if kind != "absolute" else None,
        )
        self.session.add(policy)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def update(
        self,
        policy: DeadlinePolicy,
        *,
        label: dict | None = None,
        kind: str | None = None,
        absolute_at: datetime | None = None,
        offset_days: int | None = None,
    ) -> DeadlinePolicy:
        if label is not None:
            policy.label = label
        if kind is not None:
            policy.kind = kind
        # Wert-Felder passend zum (ggf. neuen) kind setzen; das jeweils andere leeren.
        effective_kind = kind if kind is not None else policy.kind
        if effective_kind == "absolute":
            if absolute_at is not None:
                policy.absolute_at = absolute_at
            policy.offset_days = None
        else:
            if offset_days is not None:
                policy.offset_days = offset_days
            policy.absolute_at = None
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def delete(self, policy: DeadlinePolicy) -> None:
        await self.session.delete(policy)
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
