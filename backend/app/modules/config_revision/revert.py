"""Revert eines Config-Changes aus dem Audit-Log (#config-versioning, audit.revert).

Semantik: *Vorgänger-Snapshot wiederherstellen, bei Konflikt blockieren.*

Der Audit-Eintrag verlinkt per ``data.revisionId`` den Snapshot **nach** der Änderung
(``R``); der Revert spielt dessen Vorgänger ``P = R.prev`` als neue aktive Version
zurück — aber **nur**, wenn die Entität seither nicht weiter geändert wurde
(``head == R``), sonst ``409`` (zuerst die neuere Änderung zurücknehmen). Der Revert
ist selbst ein ``config_revert``-Audit-Eintrag mit eigener ``revisionId`` → selbst
revertierbar (Revert eines Reverts = Redo).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.config_revision.reapply import reapply_snapshot
from app.modules.config_revision.service import ConfigRevisionService
from app.shared.errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class RevertResult:
    entity_type: str
    entity_id: str
    reverted_audit_id: int


class RevertService:
    """Orchestriert den Audit-Log-Revert (an eine ``AsyncSession`` gebunden)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def revert(self, audit_entry_id: int, actor: str) -> RevertResult:
        """Den durch ``audit_entry_id`` beschriebenen Config-Change zurücknehmen.

        404 wenn Eintrag/Revision fehlt; 409 wenn der Eintrag nicht revertierbar ist
        (kein verlinkter Snapshot / kein Vorgänger) oder die Entität seither geändert
        wurde (stale).
        """
        entry = (
            await self.session.execute(
                select(AuditEntry).where(AuditEntry.id == audit_entry_id)
            )
        ).scalar_one_or_none()
        if entry is None:
            raise NotFoundError(f"audit entry {audit_entry_id} not found")

        revision_id = (entry.data or {}).get("revisionId")
        if not revision_id:
            raise ConflictError(
                "This audit entry has no revertable config snapshot.",
                code="not_revertable",
            )

        revisions = ConfigRevisionService(self.session)
        recorded = await revisions.get(revision_id)
        if recorded is None:
            raise NotFoundError(f"config revision {revision_id} not found")

        if recorded.prev_revision_id is None:
            raise ConflictError(
                "Cannot revert the first config state (nothing to revert to).",
                code="nothing_to_revert",
            )
        prev = await revisions.get(recorded.prev_revision_id)
        if prev is None:  # pragma: no cover - prev ist append-only, kann nicht fehlen
            raise NotFoundError("previous config revision not found")

        head = await revisions.head(recorded.entity_type, recorded.entity_id)
        if head is None or head.id != recorded.id:
            raise ConflictError(
                "A newer change exists for this config; revert that first.",
                code="stale_revert",
            )

        await reapply_snapshot(
            self.session,
            entity_type=prev.entity_type,
            entity_id=prev.entity_id,
            snapshot=prev.snapshot or {},
            actor=actor,
            action=AuditAction.CONFIG_REVERT,
            extra_data={
                "revertedAuditId": entry.id,
                "revertedRevisionId": str(recorded.id),
            },
        )
        return RevertResult(
            entity_type=recorded.entity_type,
            entity_id=recorded.entity_id,
            reverted_audit_id=entry.id,
        )
