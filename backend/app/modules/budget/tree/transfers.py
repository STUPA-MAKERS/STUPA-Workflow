"""Cost-centre to cost-centre transfers (paired expense/income bookings)."""

from __future__ import annotations

import uuid

from app.modules.audit.actions import AuditAction
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import BudgetExpense
from app.modules.budget.tree_schemas import TransferCreate, TransferOut
from app.shared.errors import ValidationProblem


class TransferOps(BudgetTreeServiceBase):
    """Create transfers as an expense on the source + income on the target."""

    async def create_transfer(self, payload: TransferCreate, *, actor: str) -> TransferOut:
        """Transfer between cost centres: expense on source + income on target
        (same fiscal year)."""
        src = await self._get_node(payload.from_budget_id)
        dst = await self._get_node(payload.to_budget_id)
        # The fiscal year must belong to the top level of BOTH cost centres.
        fy_src = await self._resolve_fiscal_year(src, payload.fiscal_year_id)
        fy_dst = await self._resolve_fiscal_year(dst, payload.fiscal_year_id)
        if fy_src != fy_dst:
            raise ValidationProblem(
                "Both cost centres must share the fiscal year.",
                errors=[{"field": "fiscalYearId", "msg": "must match for both"}],
            )
        transfer_id = uuid.uuid4()
        out_row = BudgetExpense(
            id=uuid.uuid4(),
            budget_id=src.id,
            fiscal_year_id=fy_src,
            transfer_id=transfer_id,
            kind="expense",
            amount=payload.amount,
            currency=src.currency,
            description=payload.description,
            actor=actor,
        )
        in_row = BudgetExpense(
            id=uuid.uuid4(),
            budget_id=dst.id,
            fiscal_year_id=fy_dst,
            transfer_id=transfer_id,
            kind="income",
            amount=payload.amount,
            currency=dst.currency,
            description=payload.description,
            actor=actor,
        )
        self.session.add_all([out_row, in_row])
        await self._audit(
            AuditAction.BUDGET_TRANSFER_CREATE,
            target_type="budget_transfer",
            target_id=str(transfer_id),
            data={
                "fromBudgetId": str(src.id),
                "toBudgetId": str(dst.id),
                "fiscalYearId": str(fy_src),
                "amount": str(payload.amount),
            },
        )
        await self.session.commit()
        return TransferOut(transferId=transfer_id, expenseId=out_row.id, incomeId=in_row.id)
