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

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.hashing import canonical_payload, compute_hash
from app.modules.audit.models import AuditEntry
from app.shared.paging import Page

# Fixer Advisory-Lock-Schlüssel: serialisiert Ketten-Appends prozessübergreifend.
_CHAIN_LOCK_KEY = 0x4155_4449_5400  # "AUDIT\0"


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
