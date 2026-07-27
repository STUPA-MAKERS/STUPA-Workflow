"""Audit-log revert of budget and money mutations."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.budget.tree.allocations import AllocationOps
from app.modules.budget.tree.expenses import ExpenseOps
from app.modules.budget.tree.nodes import NodeOps
from app.modules.budget.tree.service_base import _json_safe
from app.modules.budget.tree_models import Budget, BudgetExpense, Invoice
from app.modules.budget.tree_schemas import AllocationSet, BudgetNodeUpdate, ExpenseUpdate
from app.shared.errors import ConflictError


class RevertOps(NodeOps, AllocationOps, ExpenseOps):
    """Undo audited budget mutations from the audit log."""

    async def revert_audit(self, entry: AuditEntry, actor: str) -> None:
        """Undo an audited budget or money mutation from the audit log.

        The method dispatches on `entry.action` to the matching inverse. It
        deletes an additive action, that is a booking, a transfer or a
        cost-center create. It restores an update from the prior state in the
        audit `data`. Every path writes its own audit entry. A delete is
        deliberately not revertable.

        Raises:
            ConflictError: `stale_revert` (409) when the entity changed since
                the audited action. `already_reverted` (409) when the target no
                longer exists. `not_revertable` (409) for an action without an
                inverse.
        """
        self.actor = actor
        action = entry.action
        data = entry.data or {}
        target_id = entry.target_id or ""
        if action == AuditAction.BUDGET_EXPENSE_CREATE:
            await self._revert_expense_create(UUID(target_id), entry.id)
        elif action == AuditAction.BUDGET_TRANSFER_CREATE:
            await self._revert_transfer_create(UUID(target_id), entry.id)
        elif action == AuditAction.BUDGET_NODE_CREATE:
            await self._revert_node_create(UUID(target_id))
        elif action == AuditAction.BUDGET_NODE_UPDATE:
            await self._revert_node_update(UUID(target_id), data)
        elif action == AuditAction.BUDGET_ALLOCATION_SET:
            await self._revert_allocation_set(UUID(target_id), data, entry.id)
        elif action == AuditAction.BUDGET_EXPENSE_UPDATE:
            await self._revert_expense_update(UUID(target_id), data)
        else:  # pragma: no cover - the dispatcher only passes revertable actions
            raise ConflictError(
                "This budget action cannot be reverted.", code="not_revertable"
            )

    async def _revert_expense_create(
        self, expense_id: UUID, reverted_audit_id: int
    ) -> None:
        """Delete the booking and re-open an invoice that the booking set to paid."""
        expense = await self.session.get(BudgetExpense, expense_id)
        if expense is None:
            raise ConflictError(
                "Booking already removed; nothing to revert.", code="already_reverted"
            )
        if expense.invoice_id is not None:
            inv = await self.session.get(Invoice, expense.invoice_id)
            if inv is not None and inv.status == "paid":
                inv.status = "open"
                await self._audit(
                    AuditAction.BUDGET_INVOICE_UPDATE,
                    target_type="invoice",
                    target_id=str(inv.id),
                    data={"status": "open", "reason": "expense_revert"},
                )
        await self._audit(
            AuditAction.BUDGET_EXPENSE_DELETE,
            target_type="budget_expense",
            target_id=str(expense_id),
            data={
                "budgetId": str(expense.budget_id),
                "kind": expense.kind,
                "amount": str(expense.amount),
                "reverted": True,
                "revertedAuditId": reverted_audit_id,
            },
        )
        await self.session.delete(expense)
        await self.session.commit()

    async def _revert_transfer_create(
        self, transfer_id: UUID, reverted_audit_id: int
    ) -> None:
        """Delete both rows of a transfer, the expense and the income."""
        rows = (
            (
                await self.session.execute(
                    select(BudgetExpense).where(
                        BudgetExpense.transfer_id == transfer_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise ConflictError(
                "Transfer already removed; nothing to revert.", code="already_reverted"
            )
        await self._audit(
            AuditAction.BUDGET_EXPENSE_DELETE,
            target_type="budget_transfer",
            target_id=str(transfer_id),
            data={
                "amount": str(rows[0].amount),
                "reverted": True,
                "revertedAuditId": reverted_audit_id,
            },
        )
        for e in rows:
            await self.session.delete(e)
        await self.session.commit()

    async def _revert_node_create(self, budget_id: UUID) -> None:
        """Delete the cost center that the audited create action added.

        Raises:
            ConflictError: The cost center is now in use (409).
        """
        node = await self.session.get(Budget, budget_id)
        if node is None:
            raise ConflictError(
                "Cost centre already removed; nothing to revert.",
                code="already_reverted",
            )
        # delete_node runs the guard checks and answers 409 when the node is
        # still in use. It also writes the audit entry and commits.
        await self.delete_node(budget_id)

    @staticmethod
    def _value_matches(current: object, expected: object) -> bool:
        """Tell if `current` still matches the recorded `expected` value.

        Numbers compare by value, so the database roundtrip does not distort the
        scale. An example is "70" recorded against "70.00" read back. Every
        other value compares exactly.
        """
        if current == expected:
            return True
        try:
            return Decimal(str(current)) == Decimal(str(expected))
        except (InvalidOperation, ValueError):
            return False

    def _assert_not_stale(self, obj: object, after: object) -> None:
        """Guard an update revert against a newer change.

        Every field value that the audited action recorded in `after` must still
        match the current state. Otherwise the entity changed since and the
        revert would overwrite foreign changes. When `after` is no mapping, the
        revert restores the prior values as a best effort.

        Raises:
            ConflictError: `stale_revert` (409) when a value no longer matches.
        """
        if not isinstance(after, dict):
            return
        for field, expected in after.items():
            if not self._value_matches(_json_safe(getattr(obj, field, None)), expected):
                raise ConflictError(
                    "Changed since; revert the newer change first.",
                    code="stale_revert",
                )

    async def _revert_node_update(self, budget_id: UUID, data: dict) -> None:
        """Write back the prior values that the cost-center update recorded."""
        before = data.get("before")
        if not isinstance(before, dict) or not before:
            raise ConflictError(
                "No prior state recorded for this change.", code="not_revertable"
            )
        node = await self.session.get(Budget, budget_id)
        if node is None:
            raise ConflictError(
                "Cost centre no longer exists.", code="already_reverted"
            )
        self._assert_not_stale(node, data.get("after"))
        await self.update_node(budget_id, BudgetNodeUpdate(**before))

    async def _revert_allocation_set(
        self, budget_id: UUID, data: dict, reverted_audit_id: int
    ) -> None:
        """Restore the prior allocation value, or drop the row when there was none."""
        fy_raw = data.get("fiscalYearId")
        if not fy_raw:
            raise ConflictError("No fiscal year recorded.", code="not_revertable")
        fiscal_year_id = UUID(fy_raw)
        cur = await self._allocation(budget_id, fiscal_year_id)
        set_value = data.get("allocated")
        if (
            cur is None
            or set_value is None
            or Decimal(str(cur.allocated)) != Decimal(str(set_value))
        ):
            raise ConflictError(
                "Allocation changed since; revert the newer change first.",
                code="stale_revert",
            )
        previous = data.get("previousAllocated")
        if previous is None:
            # The action set the allocation for the first time. The revert
            # removes the row again.
            await self._audit(
                AuditAction.BUDGET_ALLOCATION_SET,
                target_type="budget_allocation",
                target_id=str(budget_id),
                data={
                    "fiscalYearId": str(fiscal_year_id),
                    "allocated": None,
                    "reverted": True,
                    "revertedAuditId": reverted_audit_id,
                },
            )
            await self.session.delete(cur)
            await self.session.commit()
        else:
            # set_allocation re-validates the top-down constraints, writes the
            # audit entry and commits.
            await self.set_allocation(
                budget_id, fiscal_year_id, AllocationSet(allocated=Decimal(previous))
            )

    async def _revert_expense_update(self, expense_id: UUID, data: dict) -> None:
        """Write back the prior values that the booking update recorded."""
        before = data.get("before")
        if not isinstance(before, dict) or not before:
            raise ConflictError(
                "No prior state recorded for this change.", code="not_revertable"
            )
        expense = await self.session.get(BudgetExpense, expense_id)
        if expense is None:
            raise ConflictError("Booking no longer exists.", code="already_reverted")
        # Every field that the audited action set must be unchanged, not only
        # the amount.
        self._assert_not_stale(expense, data.get("after"))
        await self.update_expense(expense_id, ExpenseUpdate(**before))
