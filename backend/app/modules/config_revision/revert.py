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
from app.modules.auth.principal import Principal
from app.modules.config_revision.reapply import reapply_snapshot
from app.modules.config_revision.service import (
    ENTITY_FLOW,
    ENTITY_FORM,
    ENTITY_SITE_CONFIG,
    ConfigRevisionService,
)
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError

# Per-Entität-Permission, die der *ursprüngliche* Config-Change verlangt hätte —
# identisch zum Sidebar-Restore-Gate (config_revision/router._RESTORE_PERM). Ein
# Audit-Revert ist eine gleich starke (Config-)Mutation und muss dieselbe granulare
# Permission verlangen, nicht nur das globale ``audit.revert`` (#AUD-018).
_CONFIG_REVERT_PERM: dict[str, str] = {
    ENTITY_FORM: "form.configure",
    ENTITY_FLOW: "flow.configure",
    ENTITY_SITE_CONFIG: "admin.site",
}

# Budget-/Geld-Mutationen: dieselbe Permission, die die ursprüngliche Mutation
# verlangte. Struktur (Knoten/Zuteilung) → ``budget.structure``; Buchungen/Umbuchungen
# bewegen Geld → ``budget.book`` (vgl. budget/tree_router).
_BUDGET_REVERT_PERM: dict[AuditAction, str] = {
    AuditAction.BUDGET_NODE_CREATE: "budget.structure",
    AuditAction.BUDGET_NODE_UPDATE: "budget.structure",
    AuditAction.BUDGET_ALLOCATION_SET: "budget.structure",
    AuditAction.BUDGET_TRANSFER_CREATE: "budget.book",
    AuditAction.BUDGET_EXPENSE_CREATE: "budget.book",
    AuditAction.BUDGET_EXPENSE_UPDATE: "budget.book",
}


@dataclass(frozen=True, slots=True)
class RevertResult:
    entity_type: str
    entity_id: str
    reverted_audit_id: int


class RevertService:
    """Orchestriert den Audit-Log-Revert (an eine ``AsyncSession`` gebunden)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def revert(
        self,
        audit_entry_id: int,
        actor: str,
        principal: Principal | None = None,
    ) -> RevertResult:
        """Den durch ``audit_entry_id`` beschriebenen Vorgang zurücknehmen.

        404 wenn der Eintrag fehlt; 409 wenn er nicht revertierbar ist
        (``not_revertable``), die Entität seither geändert wurde (``stale_revert``) oder
        das Ziel nicht mehr existiert (``already_reverted``).

        Ein Audit-Revert ist eine gleich starke Mutation wie der ursprüngliche Vorgang
        (Config-Restore, Geld-Inverse, Status-Rücksetzung). Daher wird — zusätzlich zur
        ``audit.revert``-Gatung am Router — die *granulare* Permission des Original-
        Vorgangs re-asserted (#AUD-018): ohne sie 403, damit eine delegierte
        ``audit.revert``-Rolle keine Config-/Geld-Hoheit über alle Gremien erlangt.
        ``principal=None`` (interne Aufrufer/Tests) überspringt die Re-Assertion; der
        Produktiv-Pfad (Router) reicht immer den Principal durch."""
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
            return await self._revert_config(entry, actor, principal)
        # Antrags-Zustandsübergang.
        if entry.action == AuditAction.STATUS_CHANGE:
            return await self._revert_status(entry, actor, principal)
        # Budget-/Geld-Mutation.
        if entry.action in REVERTABLE_BUDGET_ACTIONS:
            return await self._revert_budget(entry, actor, principal)
        raise ConflictError(
            "This audit entry is not revertable.", code="not_revertable"
        )

    @staticmethod
    def _require(principal: Principal | None, perm: str, what: str) -> None:
        """Re-Assert der Original-Permission (zusätzlich zu ``audit.revert``).

        ``principal=None`` (interne Aufrufer/Tests) wird nicht geprüft."""
        if principal is not None and not principal.has(perm):
            raise ForbiddenError(
                f"Missing permission to revert {what} (requires {perm})."
            )

    # --------------------------------------------------------------- config
    async def _revert_config(
        self, entry: AuditEntry, actor: str, principal: Principal | None
    ) -> RevertResult:
        """Config-Change zurücknehmen: Vorgänger-Snapshot als neue aktive Version."""
        revision_id = str((entry.data or {}).get("revisionId") or "")
        revisions = ConfigRevisionService(self.session)
        recorded = await revisions.get(revision_id)
        if recorded is None:
            raise NotFoundError(f"config revision {revision_id} not found")

        perm = _CONFIG_REVERT_PERM.get(recorded.entity_type)
        if perm is None:
            raise ForbiddenError(
                f"Cannot revert unknown config entity {recorded.entity_type}."
            )
        self._require(principal, perm, f"{recorded.entity_type} config")

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
    async def _revert_status(
        self, entry: AuditEntry, actor: str, principal: Principal | None
    ) -> RevertResult:
        """Antrags-Zustandsübergang zurücknehmen (Antrag in den Vorzustand)."""
        from app.modules.flow.service import FlowService

        # Eine Status-Rücksetzung ist ein Zustandsübergang → dieselbe Permission wie das
        # manuelle Feuern eines Übergangs (flow/router.MANAGE_PERMISSION).
        self._require(principal, "application.transition", "an application status change")

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
    async def _revert_budget(
        self, entry: AuditEntry, actor: str, principal: Principal | None
    ) -> RevertResult:
        """Budget-/Geld-Mutation zurücknehmen (Inverse je Aktionstyp)."""
        from app.modules.budget.tree_service import BudgetTreeService

        perm = _BUDGET_REVERT_PERM.get(AuditAction(entry.action))
        if perm is None:  # pragma: no cover - durch REVERTABLE_BUDGET_ACTIONS gedeckt
            raise ConflictError(
                "This audit entry is not revertable.", code="not_revertable"
            )
        self._require(principal, perm, "a budget money mutation")

        await BudgetTreeService(self.session, actor=actor).revert_audit(entry, actor)
        return RevertResult(
            entity_type=entry.target_type or "budget",
            entity_id=entry.target_id or "",
            reverted_audit_id=entry.id,
        )
