"""Revert an audited operation from the audit log (``audit.revert``).

:class:`RevertService` dispatches by audit entry: config changes (detected via
``data.revisionId``) replay the predecessor snapshot but only while the entity
is unchanged since (``head == R``, else 409); status changes reset the
application to the prior state; budget mutations apply the respective inverse
(delete additive ops, restore updates from the captured prior state). Every
revert is itself an audit entry and, where sensible, revertable.
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

# Per-entity permission the *original* config change would have required —
# identical to the sidebar restore gate. A revert is an equally strong mutation
# and must require the same granular permission, not just global ``audit.revert``.
_CONFIG_REVERT_PERM: dict[str, str] = {
    ENTITY_FORM: "form.configure",
    ENTITY_FLOW: "flow.configure",
    ENTITY_SITE_CONFIG: "admin.site",
}

# Budget mutations: same permission the original mutation required. Structure
# (nodes/allocations) -> ``budget.structure``; bookings/transfers move money
# -> ``budget.book``.
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
    """Orchestrates the audit-log revert (bound to an ``AsyncSession``)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def revert(
        self,
        audit_entry_id: int,
        actor: str,
        principal: Principal | None = None,
    ) -> RevertResult:
        """Revert the operation described by ``audit_entry_id``.

        404 if the entry is missing; 409 if not revertable, stale, or already
        reverted. Besides the router's ``audit.revert`` gate, the granular
        permission of the original operation is re-asserted (403 without it) so
        a delegated ``audit.revert`` role gains no config/money authority.
        ``principal=None`` (internal callers/tests) skips the re-assertion; the
        production path always passes the principal through."""
        entry = (
            await self.session.execute(
                select(AuditEntry).where(AuditEntry.id == audit_entry_id)
            )
        ).scalar_one_or_none()
        if entry is None:
            raise NotFoundError(f"audit entry {audit_entry_id} not found")

        data = entry.data or {}
        # Config change: carries a linked config_revision snapshot.
        if data.get("revisionId"):
            return await self._revert_config(entry, actor, principal)
        # Application status transition.
        if entry.action == AuditAction.STATUS_CHANGE:
            return await self._revert_status(entry, actor, principal)
        # Budget/money mutation.
        if entry.action in REVERTABLE_BUDGET_ACTIONS:
            return await self._revert_budget(entry, actor, principal)
        raise ConflictError(
            "This audit entry is not revertable.", code="not_revertable"
        )

    @staticmethod
    def _require(principal: Principal | None, perm: str, what: str) -> None:
        """Re-assert the original permission (in addition to ``audit.revert``).

        ``principal=None`` (internal callers/tests) is not checked."""
        if principal is not None and not principal.has(perm):
            raise ForbiddenError(
                f"Missing permission to revert {what} (requires {perm})."
            )

    # --------------------------------------------------------------- config
    async def _revert_config(
        self, entry: AuditEntry, actor: str, principal: Principal | None
    ) -> RevertResult:
        """Revert a config change: replay the predecessor snapshot as the new active version."""
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
        if prev is None:  # pragma: no cover - prev is append-only, cannot be missing
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
        """Revert an application status transition (back to the prior state)."""
        from app.modules.flow.service import FlowService

        # A status reset is a state transition, so it needs the same permission
        # as manually firing a transition.
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
        """Revert a budget/money mutation (inverse per action type)."""
        from app.modules.budget.tree.service import BudgetTreeService

        perm = _BUDGET_REVERT_PERM.get(AuditAction(entry.action))
        if perm is None:  # pragma: no cover - covered by REVERTABLE_BUDGET_ACTIONS
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
