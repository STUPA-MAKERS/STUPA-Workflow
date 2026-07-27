"""Sub-bookings of a booking, including the CAMT and MT940 file import."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.actions import AuditAction
from app.modules.budget.bank.normalize import split_leading_iban
from app.modules.budget.bank.statement import StatementParseError, parse_statement_full
from app.modules.budget.tree.expenses import ExpenseOps
from app.modules.budget.tree_models import Account, Budget, BudgetExpense
from app.modules.budget.tree_schemas import ExpenseOut, SubBookingCreate
from app.shared.errors import NotFoundError, ValidationProblem


def _subbooking_description(purpose: str | None, name: str | None) -> str:
    """Build the description of a sub-booking that comes from a file import.

    The function takes the purpose, else the counterparty name, else a
    placeholder. The `description` column is NOT NULL, so the result is never
    empty.
    """
    text = (purpose or "").strip() or (name or "").strip()
    return text or "Unterbuchung"


class SubBookingOps(ExpenseOps):
    """List, create and file-import sub-bookings of a parent booking."""

    async def list_sub_expenses(self, parent_id: UUID) -> list[ExpenseOut]:
        """Sub-bookings of a booking, oldest first."""
        parent = await self.session.get(BudgetExpense, parent_id)
        if parent is None:
            raise NotFoundError(f"budget expense {parent_id} not found")
        rows = (
            await self.session.execute(
                select(BudgetExpense, Budget.path_key, Account.name)
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .outerjoin(Account, Account.id == BudgetExpense.account_id)
                .where(BudgetExpense.parent_expense_id == parent_id)
                .order_by(BudgetExpense.created_at.asc())
            )
        ).all()
        names = await self._actor_names({e.actor for (e, _pk, _an) in rows if e.actor})
        return [
            self._expense_out(
                e, path_key, account_name=acc_name, actor_name=names.get(e.actor or "")
            )
            for (e, path_key, acc_name) in rows
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

        The child inherits the account, the cost center, the fiscal year and the
        kind from its parent. It carries its own amount, description and
        metadata. After the create the parent amount equals the sum of its
        children.
        """
        parent = await self._subbooking_parent_or_error(parent_id)
        child = BudgetExpense(
            budget_id=parent.budget_id,
            fiscal_year_id=parent.fiscal_year_id,
            account_id=parent.account_id,
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

    async def import_sub_bookings(
        self, parent_id: UUID, data: bytes, *, filename: str | None, actor: str
    ) -> list[ExpenseOut]:
        """Create sub-bookings from a CAMT.053 or MT940 file.

        Every statement line becomes a sub-booking. The child copies the
        account, the cost center, the fiscal year and the kind from the parent.
        It carries only the amount, the description, the dates and the
        reference. After the import the parent amount equals the sum of all
        children.

        Raises:
            ValidationProblem: The file does not parse, the parent is itself a
                sub-booking, or the file is over the size limit.
        """
        parent = await self._subbooking_parent_or_error(parent_id)
        if len(data) > self.settings.attachment_max_bytes:
            raise ValidationProblem(
                f"File exceeds {self.settings.attachment_max_bytes} bytes.", code="file_too_large"
            )
        try:
            lines, _balance = parse_statement_full(data, filename=filename)
        except StatementParseError as exc:
            raise ValidationProblem(
                "File is neither valid CAMT.053 nor MT940.", code="bank_statement_unparseable"
            ) from exc
        # The ledger holds EUR only. Reject a statement in another currency.
        # Otherwise abs(amount) of such a line enters the budget as EUR.
        if any((line.currency or "EUR").upper() != "EUR" for line in lines):
            raise ValidationProblem(
                "Only EUR statements are supported.", code="subbooking_currency_unsupported"
            )
        # Idempotency: a second upload of the same file must not create
        # duplicates. The parent amount is the sum of the children and would
        # double. The dedup compares the content of the existing children:
        # amount, payment date, description and reference.
        existing = (
            await self.session.scalars(
                select(BudgetExpense).where(BudgetExpense.parent_expense_id == parent.id)
            )
        ).all()

        def _key(
            amount: Decimal, pay: date | None, desc: str, ref: str | None
        ) -> tuple[object, ...]:
            return (amount, pay, desc, ref)

        seen = {_key(c.amount, c.payment_date, c.description, c.reference_number) for c in existing}
        parent_is_income = parent.kind == "income"
        created: list[BudgetExpense] = []
        for line in lines:
            magnitude = abs(line.amount)
            # A zero amount would violate the amount > 0 CHECK constraint.
            if magnitude == 0:
                continue
            # A sub-booking inherits the direction of its parent. Take only the
            # lines with the same direction. A counter booking would skew the
            # parent amount, which is the sum of the children.
            if (line.amount > 0) != parent_is_income:
                continue
            name, iban = split_leading_iban(line.counterparty_name, line.counterparty_iban)
            child = BudgetExpense(
                # copied from the parent so the roll-up and the queries work
                budget_id=parent.budget_id,
                fiscal_year_id=parent.fiscal_year_id,
                account_id=parent.account_id,
                kind=parent.kind,
                currency=parent.currency,
                parent_expense_id=parent.id,
                amount=magnitude,
                description=_subbooking_description(line.purpose, name),
                correspondent=name or None,
                payment_date=line.value_date or line.booking_date,
                reference_number=line.end_to_end_id or line.reference or None,
                actor=actor,
            )
            key = _key(child.amount, child.payment_date, child.description, child.reference_number)
            if key in seen:
                continue
            seen.add(key)
            self.session.add(child)
            created.append(child)
        await self.session.flush()
        await self._recompute_parent_amount(parent_id)
        await self._audit(
            AuditAction.BUDGET_EXPENSE_CREATE,
            target_type="budget_expense",
            target_id=str(parent_id),
            data={"subBookingsImported": len(created), "source": "file"},
        )
        await self.session.commit()
        path_key = (await self._get_node(parent.budget_id)).path_key
        names = await self._actor_names({actor})
        return [
            self._expense_out(c, path_key, actor_name=names.get(actor))
            for c in created
        ]
