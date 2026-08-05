"""Sub-bookings of a booking."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.audit.actions import AuditAction
from app.modules.budget.tree.expenses import ExpenseOps
from app.modules.budget.tree_models import Budget, BudgetExpense
from app.modules.budget.tree_schemas import ExpenseOut, SubBookingCreate
from app.shared.errors import NotFoundError, ValidationProblem


class SubBookingOps(ExpenseOps):
    """List and create sub-bookings of a parent booking."""

    async def list_sub_expenses(self, parent_id: UUID) -> list[ExpenseOut]:
        """Sub-bookings of a booking, oldest first."""
        parent = await self.session.get(BudgetExpense, parent_id)
        if parent is None:
            raise NotFoundError(f"budget expense {parent_id} not found")
        rows = (
            await self.session.execute(
                select(BudgetExpense, Budget.path_key)
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .where(BudgetExpense.parent_expense_id == parent_id)
                .order_by(BudgetExpense.created_at.asc())
            )
        ).all()
        names = await self._actor_names({e.actor for (e, _pk) in rows if e.actor})
        return [
            self._expense_out(e, path_key, actor_name=names.get(e.actor or ""))
            for (e, path_key) in rows
        ]

    async def _subbooking_parent_or_error(self, parent_id: UUID) -> BudgetExpense:
        """Load the parent booking for sub-bookings and check its invariants."""
        parent = await self.session.get(BudgetExpense, parent_id)
        if parent is None:
            raise NotFoundError(f"budget expense {parent_id} not found")
        if parent.parent_expense_id is not None:
            raise ValidationProblem("Sub-bookings cannot be nested.", code="subbooking_nested")
        if parent.transfer_id is not None:
            # A transfer booking must keep its paired amount (else net ≠ 0).
            raise ValidationProblem(
                "A transfer booking cannot be split into sub-bookings.",
                code="subbooking_on_transfer",
            )
        return parent

    async def create_sub_booking(
        self, parent_id: UUID, payload: SubBookingCreate, *, actor: str
    ) -> ExpenseOut:
        """Create a sub-booking under a parent booking.

        The child inherits the cost center, the fiscal year and the kind from
        its parent. It carries its own amount, description and metadata. After
        the create the parent amount equals the sum of its children.
        """
        parent = await self._subbooking_parent_or_error(parent_id)
        child = BudgetExpense(
            budget_id=parent.budget_id,
            fiscal_year_id=parent.fiscal_year_id,
            kind=parent.kind,
            currency=parent.currency,
            parent_expense_id=parent.id,
            amount=payload.amount,
            description=payload.description,
            invoice_date=payload.invoice_date,
            payment_date=payload.payment_date,
            correspondent=payload.correspondent,
            note=payload.note,
            reference_number=payload.reference_number,
            payment_method=payload.payment_method,
            category=payload.category,
            actor=actor,
        )
        self.session.add(child)
        await self.session.flush()
        await self._recompute_parent_amount(parent_id)
        await self._audit(
            AuditAction.BUDGET_EXPENSE_CREATE,
            target_type="budget_expense",
            target_id=str(child.id),
            data={"parentExpenseId": str(parent_id), "amount": str(child.amount)},
        )
        await self.session.commit()
        path_key = (await self._get_node(parent.budget_id)).path_key
        names = await self._actor_names({actor})
        return self._expense_out(child, path_key, actor_name=names.get(actor))
