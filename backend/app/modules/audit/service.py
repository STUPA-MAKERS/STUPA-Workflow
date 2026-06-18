"""Audit-Service (T-23): append-only Schreiben + Ketten-Verifikation + Abfrage.

* :meth:`AuditService.record` — neuen Eintrag an die Hash-Kette hängen. Vor dem Lesen
  des Vorgänger-Hashes wird ein **Transaktions-Advisory-Lock** genommen → konkurrierende
  Appends serialisieren, die Kette bleibt lückenlos (kein Race auf ``prev_hash``).
* :meth:`AuditService.verify_chain` — Kette von Anfang an nachrechnen; erkennt sowohl
  manipulierte Felder (``hash``-Mismatch) als auch entfernte/eingefügte Zeilen
  (``prev_hash``-Link gebrochen).
* :meth:`AuditService.query` — gefilterte, gepagte Lesesicht (RBAC im Router).

Die Service-Hook :func:`record` kapselt den Standardfall für andere Module (T-10/14/15…):
``await record(session, actor=…, action=…, target_type=…, target_id=…, data=…)``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import REVERTABLE_BUDGET_ACTIONS, AuditAction
from app.modules.audit.hashing import canonical_payload, compute_hash
from app.modules.audit.models import AuditEntry
from app.shared.paging import Page

# Fixer Advisory-Lock-Schlüssel: serialisiert Ketten-Appends prozessübergreifend.
_CHAIN_LOCK_KEY = 0x4155_4449_5400  # "AUDIT\0"


def data_uuid_strings(data: object) -> set[str]:
    """Alle UUID-förmigen String-Werte (rekursiv) aus einem ``data``-Payload sammeln.

    Genutzt für die Klarnamen-Auflösung der in ``data`` eingebetteten Entity-Ids
    (#no-uuids-in-ui). Schlüssel werden ignoriert — nur Werte zählen."""
    found: set[str] = set()

    def walk(v: object) -> None:
        if isinstance(v, str):
            try:
                uuid.UUID(v)
            except ValueError:
                return
            found.add(v)
        elif isinstance(v, dict):
            for x in v.values():  # pyright: ignore[reportUnknownVariableType]
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:  # pyright: ignore[reportUnknownVariableType]
                walk(x)

    walk(data)
    return found


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """Ergebnis von :meth:`AuditService.verify_chain`."""

    valid: bool
    checked: int
    broken_at: int | None = None
    reason: str | None = None


class AuditService:
    """An eine ``AsyncSession`` gebundener Audit-Service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        actor: str | None,
        action: AuditAction | str,
        target_type: str | None = None,
        target_id: str | None = None,
        data: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> AuditEntry:
        """Eintrag append-only an die Kette hängen (kein Commit — Aufrufer-Transaktion).

        ``data`` darf **keine** PII-Rohwerte enthalten (nur id-Referenzen/Metadaten,
        security.md §4) — Verantwortung der aufrufenden Stelle."""
        action_value = str(action)
        payload = data or {}
        stamp = at or datetime.now(UTC)

        # Append serialisieren, damit `prev_hash` konsistent bleibt. Der Schlüssel ist
        # eine feste int-Konstante (kein User-Input) → direkt eingebettet, kein Bind nötig.
        await self.session.execute(text(f"SELECT pg_advisory_xact_lock({_CHAIN_LOCK_KEY})"))
        prev_hash = (
            await self.session.execute(
                select(AuditEntry.hash).order_by(AuditEntry.id.desc()).limit(1)
            )
        ).scalar_one_or_none()

        canonical = canonical_payload(
            actor=actor,
            action=action_value,
            target_type=target_type,
            target_id=target_id,
            at=stamp,
            data=payload,
        )
        entry = AuditEntry(
            actor=actor,
            action=action_value,
            target_type=target_type,
            target_id=target_id,
            at=stamp,
            data=payload,
            prev_hash=prev_hash,
            hash=compute_hash(prev_hash, canonical),
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def revertable_flags(
        self, entries: Sequence[AuditEntry]
    ) -> dict[int, bool]:
        """Pro Audit-Eintrag: ist er aus dem Log zurücknehmbar (#config-versioning)?

        Günstige, weitgehend statische Eigenschaft für die Liste — **keine** teuren Head-/
        Stale-Prüfungen pro Zeile (die übernimmt der Revert beim Klick, 409 sonst).
        Config-Changes ohne Vorgänger (erster Stand) sind nicht revertierbar; Budget-
        Änderungen brauchen den festgehaltenen Vorzustand. Ein Batch-Lookup löst den
        Vorgänger-Check der Config-Snapshots auf."""
        flags: dict[int, bool] = {}
        revision_ids: dict[int, str] = {}
        for e in entries:
            data = e.data or {}
            rid = data.get("revisionId")
            if rid:
                revision_ids[e.id] = str(rid)
                flags[e.id] = False  # erst nach Vorgänger-Bestätigung True
            elif e.action == AuditAction.STATUS_CHANGE:
                flags[e.id] = bool(data.get("fromStateId") and data.get("toStateId"))
            elif e.action in REVERTABLE_BUDGET_ACTIONS:
                if e.action in (
                    AuditAction.BUDGET_NODE_UPDATE,
                    AuditAction.BUDGET_EXPENSE_UPDATE,
                ):
                    flags[e.id] = bool(data.get("before"))
                elif e.action == AuditAction.BUDGET_ALLOCATION_SET:
                    flags[e.id] = "previousAllocated" in data
                else:
                    flags[e.id] = True
            else:
                flags[e.id] = False
        if revision_ids:
            from app.modules.config_revision.models import ConfigRevision

            uuid_map: dict[uuid.UUID, int] = {}
            for eid, rid in revision_ids.items():
                try:
                    uuid_map[uuid.UUID(rid)] = eid
                except ValueError:
                    continue  # defensiv: revisionId ist normalerweise immer eine UUID
            if uuid_map:
                rows = (
                    await self.session.execute(
                        select(
                            ConfigRevision.id, ConfigRevision.prev_revision_id
                        ).where(ConfigRevision.id.in_(uuid_map.keys()))
                    )
                ).all()
                for rev_id, prev_id in rows:
                    eid = uuid_map.get(rev_id)
                    if eid is not None:
                        flags[eid] = prev_id is not None
        return flags

    async def verify_chain(self) -> ChainVerification:
        """Kette ab Genesis nachrechnen; erster Bruch wird gemeldet (fail-closed).

        Streamt zeilenweise (server-side cursor) statt die gesamte Kette in den Speicher
        zu laden — auch sehr lange Audit-Logs bleiben verifizierbar."""
        prev_hash: bytes | None = None
        checked = 0
        stream = await self.session.stream_scalars(
            select(AuditEntry).order_by(AuditEntry.id.asc())
        )
        async for entry in stream:
            if entry.prev_hash != prev_hash:
                return ChainVerification(
                    valid=False,
                    checked=checked,
                    broken_at=entry.id,
                    reason="prev_hash_mismatch",
                )
            canonical = canonical_payload(
                actor=entry.actor,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                at=entry.at,
                data=entry.data,
            )
            if compute_hash(entry.prev_hash, canonical) != entry.hash:
                return ChainVerification(
                    valid=False,
                    checked=checked,
                    broken_at=entry.id,
                    reason="hash_mismatch",
                )
            prev_hash = entry.hash
            checked += 1
        return ChainVerification(valid=True, checked=checked)

    async def query(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[AuditEntry]:
        """Gefilterte, absteigend (neueste zuerst) gepagte Audit-Sicht."""
        stmt: Select[tuple[AuditEntry]] = select(AuditEntry)
        if action is not None:
            stmt = stmt.where(AuditEntry.action == action)
        if actor is not None:
            stmt = stmt.where(AuditEntry.actor == actor)
        if target_type is not None:
            stmt = stmt.where(AuditEntry.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditEntry.target_id == target_id)
        if since is not None:
            stmt = stmt.where(AuditEntry.at >= since)
        if until is not None:
            stmt = stmt.where(AuditEntry.at <= until)

        total = (
            await self.session.execute(
                select(func.count()).select_from(stmt.subquery())
            )
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AuditEntry.id.desc()).limit(limit).offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return Page(items=list(rows), total=total, limit=limit, offset=offset)

    async def query_cursor(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        before: int | None = None,
        limit: int = 50,
    ) -> tuple[list[AuditEntry], bool]:
        """Keyset-gepagte Audit-Sicht (``id`` desc). Gibt (items, has_more) zurück.

        ``before`` = Keyset-Cursor (nur Einträge mit ``id < before``). Es wird
        ``limit + 1`` gelesen, um ``has_more`` ohne separaten COUNT zu bestimmen
        (skaliert auf sehr lange Logs)."""
        stmt: Select[tuple[AuditEntry]] = select(AuditEntry)
        if action is not None:
            stmt = stmt.where(AuditEntry.action == action)
        if actor is not None:
            stmt = stmt.where(AuditEntry.actor == actor)
        if since is not None:
            stmt = stmt.where(AuditEntry.at >= since)
        if until is not None:
            stmt = stmt.where(AuditEntry.at <= until)
        if before is not None:
            stmt = stmt.where(AuditEntry.id < before)

        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AuditEntry.id.desc()).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        has_more = len(rows) > limit
        return list(rows[:limit]), has_more

    async def resolve_actor_names(
        self, subs: Sequence[str | None]
    ) -> dict[str, str | None]:
        """``sub`` → Klarname (``display_name`` bevorzugt, sonst ``email``).

        Batch-Auflösung über die ``principal``-Tabelle. Unbekannte/None-``sub`` fehlen
        in der Map (Aufrufer fällt auf ``sub`` bzw. „System" zurück)."""
        from app.modules.auth.models import Principal

        wanted = {s for s in subs if s}
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(Principal.sub, Principal.display_name, Principal.email).where(
                    Principal.sub.in_(wanted)
                )
            )
        ).all()
        return {sub: (display_name or email) for sub, display_name, email in rows}

    async def resolve_target_labels(
        self, targets: Sequence[tuple[str | None, str | None]]
    ) -> dict[tuple[str, str], str]:
        """``(target_type, target_id)`` → menschenlesbares Ziel-Label (Batch, #2).

        Best effort für die Audit-UI: nur Typen mit Namensquelle werden aufgelöst
        (Antragstitel, Gremium-/Rollen-/Webhook-Name, …); gelöschte Ziele oder
        nicht-UUID-Ids fehlen in der Map — das FE fällt auf ``type:id`` zurück.
        Keine PII über die Lesesicht hinaus: alles hier ist Principals mit
        ``audit.read`` ohnehin über die jeweiligen Admin-Sichten zugänglich."""
        by_type: dict[str, set[uuid.UUID]] = {}
        for target_type, target_id in targets:
            if not target_type or not target_id:
                continue
            try:
                by_type.setdefault(target_type, set()).add(uuid.UUID(target_id))
            except ValueError:
                continue  # z. B. export-Dateinamen — target_id ist selbst das Label

        labels: dict[tuple[str, str], str] = {}

        async def fill(
            target_type: str, stmt: Select[tuple[uuid.UUID, Any]]
        ) -> None:
            for row_id, label in (await self.session.execute(stmt)).all():
                if label:
                    labels[(target_type, str(row_id))] = label

        def i18n_label(m: object) -> str | None:
            if not isinstance(m, dict) or not m:
                return None
            return m.get("de") or next(iter(m.values()), None)

        if ids := by_type.get("application"):
            from app.modules.applications.models import Application

            rows = (
                await self.session.execute(
                    select(Application.id, Application.data).where(
                        Application.id.in_(ids)
                    )
                )
            ).all()
            for row_id, data in rows:
                title = (data or {}).get("title")
                if isinstance(title, str) and title.strip():
                    labels[("application", str(row_id))] = title.strip()
        if ids := by_type.get("gremium"):
            from app.modules.admin.models import Gremium

            await fill(
                "gremium", select(Gremium.id, Gremium.name).where(Gremium.id.in_(ids))
            )
        if ids := by_type.get("application_type"):
            from app.modules.admin.models import ApplicationType

            rows = (
                await self.session.execute(
                    select(ApplicationType.id, ApplicationType.name_i18n).where(
                        ApplicationType.id.in_(ids)
                    )
                )
            ).all()
            for row_id, name_i18n in rows:
                if label := i18n_label(name_i18n):
                    labels[("application_type", str(row_id))] = label
        if ids := by_type.get("role"):
            from app.modules.auth.models import Role

            rows = (
                await self.session.execute(
                    select(Role.id, Role.name_i18n, Role.key).where(Role.id.in_(ids))
                )
            ).all()
            for row_id, name_i18n, key in rows:
                if label := i18n_label(name_i18n) or key:
                    labels[("role", str(row_id))] = label
        if ids := by_type.get("principal"):
            from app.modules.auth.models import Principal

            rows = (
                await self.session.execute(
                    select(
                        Principal.id, Principal.display_name, Principal.email
                    ).where(Principal.id.in_(ids))
                )
            ).all()
            for row_id, display_name, email in rows:
                if label := display_name or email:
                    labels[("principal", str(row_id))] = label
        if ids := by_type.get("webhook"):
            from app.modules.admin.models import Webhook

            await fill(
                "webhook", select(Webhook.id, Webhook.name).where(Webhook.id.in_(ids))
            )
        if ids := by_type.get("vote"):
            from app.modules.voting.models import Vote

            await fill("vote", select(Vote.id, Vote.question).where(Vote.id.in_(ids)))
        if ids := by_type.get("attachment"):
            from app.modules.files.models import Attachment

            await fill(
                "attachment",
                select(Attachment.id, Attachment.filename).where(
                    Attachment.id.in_(ids)
                ),
            )
        return labels

    async def resolve_data_ids(
        self, data_dicts: Sequence[dict[str, Any] | None]
    ) -> dict[str, str]:
        """UUIDs in den ``data``-Payloads → Klarname (Batch, #no-uuids-in-ui).

        ``data`` trägt unbenannte Entity-Referenzen (``meetingId``, ``gremiumId``,
        ``budgetId``, ``fiscalYearId``, ``applicationId``, …) als rohe UUIDs. Da die
        Schlüssel **nicht** typisiert sind, werden alle UUID-förmigen Werte (rekursiv)
        gesammelt und je Tabelle per ``id IN (...)`` aufgelöst — UUIDs sind global
        eindeutig, daher keine Kollision. Nicht auflösbare/gelöschte Ids fehlen in der
        Map; das FE zeigt dann die rohe UUID. Keine zusätzliche PII-Exposition (alles
        hier ist für ``audit.read``-Principals ohnehin über die Admin-Sichten sichtbar).
        """
        candidates: set[uuid.UUID] = set()
        for d in data_dicts:
            for s in data_uuid_strings(d):
                candidates.add(uuid.UUID(s))
        if not candidates:
            return {}

        labels: dict[str, str] = {}

        def i18n_label(m: object) -> str | None:
            if not isinstance(m, dict) or not m:
                return None
            return m.get("de") or next(iter(m.values()), None)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]

        async def fill(stmt: Select[tuple[uuid.UUID, Any]]) -> None:
            for row_id, label in (await self.session.execute(stmt)).all():
                if label and str(row_id) not in labels:
                    labels[str(row_id)] = label

        from app.modules.admin.models import ApplicationType, Gremium, Webhook
        from app.modules.applications.models import Application
        from app.modules.auth.models import Principal, Role
        from app.modules.budget.tree_models import Budget, FiscalYear
        from app.modules.files.models import Attachment
        from app.modules.livevote.models import Meeting
        from app.modules.voting.models import Vote

        # Antrag: Titel steckt im JSONB-``data`` (kein Spalten-Label).
        for row_id, data in (
            await self.session.execute(
                select(Application.id, Application.data).where(
                    Application.id.in_(candidates)
                )
            )
        ).all():
            title = (data or {}).get("title")
            if isinstance(title, str) and title.strip():
                labels[str(row_id)] = title.strip()

        await fill(select(Gremium.id, Gremium.name).where(Gremium.id.in_(candidates)))
        await fill(select(Budget.id, Budget.name).where(Budget.id.in_(candidates)))
        await fill(select(Meeting.id, Meeting.title).where(Meeting.id.in_(candidates)))
        await fill(select(Webhook.id, Webhook.name).where(Webhook.id.in_(candidates)))
        await fill(select(Vote.id, Vote.question).where(Vote.id.in_(candidates)))
        await fill(
            select(Attachment.id, Attachment.filename).where(
                Attachment.id.in_(candidates)
            )
        )

        # Mehrspaltige / abgeleitete Labels (Reihenfolge egal — ``fill`` überschreibt nie).
        for row_id, display_name, email in (
            await self.session.execute(
                select(Principal.id, Principal.display_name, Principal.email).where(
                    Principal.id.in_(candidates)
                )
            )
        ).all():
            if (label := display_name or email) and str(row_id) not in labels:
                labels[str(row_id)] = label
        for row_id, name_i18n, key in (
            await self.session.execute(
                select(Role.id, Role.name_i18n, Role.key).where(
                    Role.id.in_(candidates)
                )
            )
        ).all():
            if (label := i18n_label(name_i18n) or key) and str(row_id) not in labels:
                labels[str(row_id)] = label
        for row_id, name_i18n in (
            await self.session.execute(
                select(ApplicationType.id, ApplicationType.name_i18n).where(
                    ApplicationType.id.in_(candidates)
                )
            )
        ).all():
            if (label := i18n_label(name_i18n)) and str(row_id) not in labels:
                labels[str(row_id)] = label
        for row_id, year in (
            await self.session.execute(
                select(FiscalYear.id, FiscalYear.year).where(
                    FiscalYear.id.in_(candidates)
                )
            )
        ).all():
            if str(row_id) not in labels:
                labels[str(row_id)] = str(year)
        return labels

    async def list_actors(self) -> list[tuple[str, str | None]]:
        """Distinkte Akteure (``sub``) des Logs + aufgelöster Klarname (für Filter)."""
        subs = (
            (
                await self.session.execute(
                    select(AuditEntry.actor)
                    .where(AuditEntry.actor.is_not(None))
                    .distinct()
                    .order_by(AuditEntry.actor)
                )
            )
            .scalars()
            .all()
        )
        actor_subs = [s for s in subs if s is not None]
        names = await self.resolve_actor_names(actor_subs)
        return [(sub, names.get(sub)) for sub in actor_subs]


async def record(
    session: AsyncSession,
    *,
    actor: str | None,
    action: AuditAction | str,
    target_type: str | None = None,
    target_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEntry:
    """Service-Hook für andere Module: einen Audit-Eintrag schreiben (kein Commit)."""
    return await AuditService(session).record(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        data=data,
    )
