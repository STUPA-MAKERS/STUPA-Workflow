"""Revert eines auditierten Vorgangs aus dem Audit-Log (#config-versioning, audit.revert).

Der :class:`RevertService` ist der zentrale Dispatcher. Anhand des Audit-Eintrags wird
der passende Rücknahme-Pfad gewählt:

* **Config-Changes** (Form/Flow/Branding — erkennbar an ``data.revisionId``): der
  Vorgänger-Snapshot ``P = R.prev`` wird als neue aktive Version zurückgespielt — aber
  **nur**, wenn die Entität seither nicht weiter geändert wurde (``head == R``), sonst
  ``409``. Der erste Stand (kein Vorgänger) ist nicht revertierbar.
* **Antrags-Zustandsübergänge** (``status_change``): der Antrag wird in den Vorzustand
  zurückgesetzt (best effort, nur wenn er noch im Ziel-State steht).
* **Budget-/Geld-Mutationen** (Buchungen, Umbuchungen, Kostenstellen, Zuteilungen): die
  jeweilige Inverse — additive Vorgänge löschen, Änderungen aus dem festgehaltenen
  Vorzustand wiederherstellen.

Jeder Revert ist selbst ein Audit-Eintrag → (wo sinnvoll) selbst revertierbar (Redo).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import REVERTABLE_BUDGET_ACTIONS, AuditAction
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
        """Den durch ``audit_entry_id`` beschriebenen Vorgang zurücknehmen.

        404 wenn der Eintrag fehlt; 409 wenn er nicht revertierbar ist
        (``not_revertable``), die Entität seither geändert wurde (``stale_revert``) oder
        das Ziel nicht mehr existiert (``already_reverted``)."""
        entry = (
            await self.session.execute(
                select(AuditEntry).where(AuditEntry.id == audit_entry_id)
            )
        ).scalar_one_or_none()
        if entry is None:
            raise NotFoundError(f"audit entry {audit_entry_id} not found")

        data = entry.data or {}
        # Config-Change: trägt einen verlinkten config_revision-Snapshot.
        if data.get("revisionId"):
            return await self._revert_config(entry, actor)
        # Antrags-Zustandsübergang.
        if entry.action == AuditAction.STATUS_CHANGE:
            return await self._revert_status(entry, actor)
        # Budget-/Geld-Mutation.
        if entry.action in REVERTABLE_BUDGET_ACTIONS:
            return await self._revert_budget(entry, actor)
        raise ConflictError(
            "This audit entry is not revertable.", code="not_revertable"
        )

    # --------------------------------------------------------------- config
    async def _revert_config(self, entry: AuditEntry, actor: str) -> RevertResult:
        """Config-Change zurücknehmen: Vorgänger-Snapshot als neue aktive Version."""
        revision_id = str((entry.data or {}).get("revisionId") or "")
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

    # --------------------------------------------------------------- status
    async def _revert_status(self, entry: AuditEntry, actor: str) -> RevertResult:
        """Antrags-Zustandsübergang zurücknehmen (Antrag in den Vorzustand)."""
        from app.modules.flow.service import FlowService

        data = entry.data or {}
        app_id = entry.target_id
        from_raw = data.get("fromStateId")
        to_raw = data.get("toStateId")
        if not app_id or not from_raw or not to_raw:
            raise ConflictError(
                "This status change is not revertable.", code="not_revertable"
            )
        await FlowService(self.session).revert_status(
            UUID(app_id),
            from_state_id=UUID(from_raw),
            to_state_id=UUID(to_raw),
            actor=actor,
            reverted_audit_id=entry.id,
        )
        return RevertResult(
            entity_type="application",
            entity_id=app_id,
            reverted_audit_id=entry.id,
        )

    # --------------------------------------------------------------- budget
    async def _revert_budget(self, entry: AuditEntry, actor: str) -> RevertResult:
        """Budget-/Geld-Mutation zurücknehmen (Inverse je Aktionstyp)."""
        from app.modules.budget.tree_service import BudgetTreeService

        await BudgetTreeService(self.session, actor=actor).revert_audit(entry, actor)
        return RevertResult(
            entity_type=entry.target_type or "budget",
            entity_id=entry.target_id or "",
            reverted_audit_id=entry.id,
        )
