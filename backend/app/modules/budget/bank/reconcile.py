"""Confirm / ignore / unlink staged statement lines.

Confirming a line in the review dialog creates a ``budget_expense`` (via
:meth:`BudgetTreeService.book_expense`, incl. its validation + audit) and a
``bank_allocation`` (line <-> booking).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.audit.actions import AuditAction
from app.modules.budget.bank import normalize
from app.modules.budget.bank.service_base import BankServiceBase
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import (
    BankAllocation,
    BankStatementLine,
    BudgetExpense,
    CounterpartyMemory,
)
from app.modules.budget.tree_schemas import (
    ConfirmLineRequest,
    ExpenseCreate,
    ExpenseOut,
    StatementLineOut,
)
from app.shared.errors import NotFoundError, ValidationProblem


class ReconcileOps(BankServiceBase):
    """Confirm (book), ignore and unlink staged statement lines."""

    async def confirm_line(self, line_id: uuid.UUID, payload: ConfirmLineRequest) -> ExpenseOut:
        """Confirm a line: create a new booking or attach to an existing one.

        Both paths create a ``bank_allocation`` and set the line to ``matched``."""
        line = await self.session.get(BankStatementLine, line_id)
        if line is None:
            raise NotFoundError(f"statement line {line_id} not found")
        if line.match_state == "matched":
            raise ValidationProblem(
                "Statement line is already matched.", code="line_already_matched"
            )

        tree = BudgetTreeService(self.session, settings=self.settings, actor=self.actor)
        kind = "income" if line.amount > 0 else "expense"
        amount = abs(line.amount)
        if amount == 0:
            raise ValidationProblem(
                "A zero-amount transaction cannot be booked.", code="line_zero_amount"
            )

        # Clean the counterparty: re-derive primarily from the SEPA raw fields
        # (``raw_payload``: ABWE+/ABWA+/IBAN+) so lines staged BEFORE the parser fix
        # also get a clean recipient/IBAN at booking. If that yields nothing (e.g.
        # CAMT/file import without GVC fields), use the stored values (possibly
        # detaching the IBAN from the name).
        clean_name, clean_iban = normalize.mt940_counterparty(
            line.raw_payload or {}, credit=line.amount > 0
        )
        if not clean_name and not clean_iban:
            clean_name, clean_iban = normalize.split_leading_iban(
                line.counterparty_name, line.counterparty_iban
            )

        # Validate the target BEFORE the claim so the claim only happens when the
        # booking will go through (minimizes the orphan window: matched without booking).
        expense: BudgetExpense | None = None
        if payload.match_expense_id is not None:
            # ``with_for_update`` locks the booking row until commit: without it,
            # two parallel confirms of different lines against the SAME booking
            # could both pass the ``already`` check and each create an allocation
            # (one payment reconciled twice) — the conditional claim UPDATE only
            # protects per statement line, not the shared booking.
            expense = await self.session.get(
                BudgetExpense, payload.match_expense_id, with_for_update=True
            )
            if expense is None:
                raise NotFoundError(f"expense {payload.match_expense_id} not found")
            if expense.kind != kind:
                raise ValidationProblem(
                    "Booking kind does not match the transaction direction.",
                    code="line_kind_mismatch",
                )
            if expense.amount != amount:
                raise ValidationProblem(
                    "Booking amount does not match the transaction amount.",
                    code="line_amount_mismatch",
                )
            if expense.account_id is not None and expense.account_id != line.account_id:
                raise ValidationProblem(
                    "Booking belongs to a different account than the statement line.",
                    code="line_account_mismatch",
                )
            already = await self.session.scalar(
                select(BankAllocation.id)
                .where(BankAllocation.expense_id == expense.id)
                .limit(1)
            )
            if already is not None:
                raise ValidationProblem(
                    "That booking is already reconciled with a transaction.",
                    code="expense_already_allocated",
                )

        # ONE transaction for claim + booking + allocation + audit: the conditional
        # claim UPDATE (match_state != 'matched') keeps the row locked until the
        # commit at the bottom, so concurrent confirms block and then see 'matched'
        # (no double booking). book_expense runs with ``commit=False`` so a failure
        # anywhere rolls back EVERYTHING — claim AND booking (no orphaned booking,
        # no double debit on retry).
        try:
            claimed = (
                await self.session.execute(
                    update(BankStatementLine)
                    .where(
                        BankStatementLine.id == line_id,
                        BankStatementLine.match_state != "matched",
                    )
                    .values(match_state="matched")
                    .returning(BankStatementLine.id)
                )
            ).first()
            if claimed is None:
                raise ValidationProblem(
                    "Statement line is already matched.", code="line_already_matched"
                )

            if expense is not None:
                expense_out = tree._expense_out(expense, None)
                expense_id = expense.id
            else:
                description = payload.description or self._default_description(
                    clean_name, line.purpose
                )
                created = await tree.book_expense(
                    ExpenseCreate(
                        amount=amount,
                        description=description,
                        kind=kind,  # type: ignore[arg-type]
                        budgetId=payload.budget_id,
                        fiscalYearId=payload.fiscal_year_id,
                        correspondent=clean_name,
                        note=self._booking_note(line, kind, name=clean_name, iban=clean_iban),
                        paymentDate=line.value_date or line.booking_date,
                        referenceNumber=line.end_to_end_id or line.reference,
                        paymentMethod="ueberweisung",
                    ),
                    actor=self.actor or "",
                    # Carry the line's account onto the booking — no manual field
                    # anymore, hence passed through explicitly here.
                    account_id=line.account_id,
                    commit=False,  # shared transaction — the commit below is the only one
                )
                expense_out = created
                expense_id = created.id

            self.session.add(
                BankAllocation(
                    id=uuid.uuid4(),
                    statement_line_id=line.id,
                    expense_id=expense_id,
                    allocated_amount=amount,
                )
            )
            if payload.budget_id is not None:
                await self._remember_counterparty(clean_iban, payload.budget_id)
            await self._audit(
                AuditAction.BANK_LINE_RECONCILE,
                target_id=str(line.id),
                data={"expenseId": str(expense_id), "kind": kind, "amount": str(amount)},
            )
            await self.session.commit()
        except Exception:
            # Everything in one transaction: a rollback takes claim + booking back
            # together; the line stays open and can be confirmed again cleanly.
            await self.session.rollback()
            raise
        return expense_out

    @staticmethod
    def _default_description(name: str | None, purpose: str | None) -> str:
        """Short description ``<purpose> – <name>`` (same format as the curated
        existing bookings); the full formatted description lives in the note.
        ``name`` is already cleaned (IBAN detached)."""
        return normalize.build_short_description(name, purpose)

    @staticmethod
    def _booking_note(
        line: BankStatementLine, kind: str, *, name: str | None, iban: str | None
    ) -> str | None:
        """Structured note (recipient/sender · IBAN · purpose · booking) for the line.
        ``name``/``iban`` are already cleaned (IBAN detached from the name).

        The Sparkasse booking time (``DATUM … UHR``) was moved to
        ``raw_payload['booking_time']`` at parse time; CAMT/other banks only have the date."""
        booking_time = (line.raw_payload or {}).get("booking_time")
        return normalize.build_booking_note(
            name=name,
            iban=iban,
            purpose=line.purpose,
            kind=kind,
            when=line.value_date or line.booking_date,
            booking_time=booking_time if isinstance(booking_time, str) else None,
        )

    async def _remember_counterparty(
        self, counterparty_iban: str | None, budget_id: uuid.UUID
    ) -> None:
        """Remember/update counterparty IBAN -> cost centre (suggestion next time)."""
        if not counterparty_iban:
            return
        stmt = (
            pg_insert(CounterpartyMemory)
            .values(id=uuid.uuid4(), counterparty_iban=counterparty_iban, budget_id=budget_id)
            .on_conflict_do_update(
                constraint="uq_counterparty_memory_iban",
                set_={"budget_id": budget_id},
            )
        )
        await self.session.execute(stmt)

    async def ignore_line(self, line_id: uuid.UUID) -> None:
        """Mark a line as irrelevant — it is kept (idempotent import)."""
        line = await self.session.get(BankStatementLine, line_id)
        if line is None:
            raise NotFoundError(f"statement line {line_id} not found")
        # Conditional claim as in confirm_line: a concurrently just-booked
        # ('matched') line must NOT be flipped back to 'ignored' via an ORM dirty
        # flush — that would decouple the reconcile state from the ledger.
        claimed = (
            await self.session.execute(
                update(BankStatementLine)
                .where(
                    BankStatementLine.id == line_id,
                    BankStatementLine.match_state != "matched",
                )
                .values(match_state="ignored")
                .returning(BankStatementLine.id)
            )
        ).first()
        if claimed is None:
            raise ValidationProblem(
                "A matched statement line cannot be ignored.", code="line_already_matched"
            )
        await self._audit(AuditAction.BANK_LINE_IGNORE, target_id=str(line_id))
        await self.session.commit()

    async def unlink_line(self, line_id: uuid.UUID) -> StatementLineOut:
        """Unlink line <-> booking: remove the ``bank_allocation`` and set the line
        back to ``unmatched``. The booking REMAINS (it is the money record; only
        the bank link is removed)."""
        line = await self.session.get(BankStatementLine, line_id)
        if line is None:
            raise NotFoundError(f"statement line {line_id} not found")
        await self.session.execute(
            delete(BankAllocation).where(BankAllocation.statement_line_id == line_id)
        )
        line.match_state = "unmatched"
        await self._audit(AuditAction.BANK_LINE_UNLINK, target_id=str(line_id))
        await self.session.commit()
        # The frontend reloads the list after unlink (incl. suggestion) — no path key needed.
        return self._line_out(line, None)
