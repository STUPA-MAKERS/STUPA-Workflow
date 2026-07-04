"""Expense/income bookings: create, update, filtered listing, delete."""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy import Text as _Text

from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.audit.actions import AuditAction
from app.modules.budget.tree.service_base import BudgetTreeServiceBase, _json_safe
from app.modules.budget.tree_models import (
    Account,
    BankAllocation,
    Budget,
    BudgetExpense,
    Invoice,
)
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import ExpenseCreate, ExpenseOut, ExpenseUpdate
from app.search import dialect_of, trigram_rank
from app.shared.errors import NotFoundError, ValidationProblem
from app.shared.paging import Page


class ExpenseOps(BudgetTreeServiceBase):
    """Book, update, list and delete expense/income bookings."""

    async def _actor_names(self, subs: set[str]) -> dict[str, str]:
        """Map booking actor (principal ``sub``) → display name (name/email/sub).

        The actor UUID must never reach the UI. Legacy actors that already are a
        name find no principal match and are absent (FE falls back to ``actor``).
        """
        from app.modules.auth.models import Principal as PrincipalRow

        wanted = {s for s in subs if s}
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(PrincipalRow.sub, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.sub.in_(wanted)
                )
            )
        ).all()
        return {sub: (dn or em or sub) for sub, dn, em in rows}

    @staticmethod
    def _expense_out(
        e: BudgetExpense,
        path_key: str | None,
        app_title: str | None = None,
        account_name: str | None = None,
        invoice_number: str | None = None,
        actor_name: str | None = None,
        child_count: int = 0,
    ) -> ExpenseOut:
        return ExpenseOut(
            id=e.id,
            budgetId=e.budget_id,
            pathKey=path_key,
            fiscalYearId=e.fiscal_year_id,
            kind=e.kind,  # type: ignore[arg-type]
            amount=e.amount,
            currency=e.currency,
            description=e.description,
            applicationId=e.application_id,
            applicationTitle=app_title,
            accountId=e.account_id,
            accountName=account_name,
            transferId=e.transfer_id,
            actor=e.actor,
            actorName=actor_name,
            invoiceDate=e.invoice_date,
            paymentDate=e.payment_date,
            correspondent=e.correspondent,
            note=e.note,
            referenceNumber=e.reference_number,
            paymentMethod=e.payment_method,  # type: ignore[arg-type]
            category=e.category,
            invoiceId=e.invoice_id,
            invoiceNumber=invoice_number,
            parentExpenseId=e.parent_expense_id,
            childCount=child_count,
            createdAt=e.created_at,
        )

    async def create_expense(
        self, budget_id: UUID, payload: ExpenseCreate, *, actor: str
    ) -> ExpenseOut:
        """(Compat) Book against the cost centre from the path (``/budgets/{id}``)."""
        return await self.book_expense(
            payload.model_copy(update={"budget_id": budget_id}), actor=actor
        )

    async def book_expense(
        self,
        payload: ExpenseCreate,
        *,
        actor: str,
        commit: bool = True,
        account_id: UUID | None = None,
    ) -> ExpenseOut:
        """Book an expense/income.

        Bound (``applicationId`` set) inherits cost centre + fiscal year from
        the application; standalone requires ``budgetId`` (FY auto-resolved).
        """
        app_title: str | None = None
        if payload.application_id is not None:
            app = await self.session.get(Application, payload.application_id)
            if app is None:
                raise NotFoundError(f"application {payload.application_id} not found")
            if app.budget_id is None or app.fiscal_year_id is None:
                raise ValidationProblem(
                    "Application has no budget/fiscal year assigned.",
                    errors=[{"field": "applicationId", "msg": "no budget assigned"}],
                )
            node = await self._get_node(app.budget_id)
            fy_id = app.fiscal_year_id
            app_title = _title_of(app.data)
        else:
            if payload.budget_id is None:
                raise ValidationProblem(
                    "budgetId is required for a standalone booking.",
                    errors=[{"field": "budgetId", "msg": "required"}],
                )
            node = await self._get_node(payload.budget_id)
            fy_id = await self._resolve_fiscal_year(node, payload.fiscal_year_id)
        # The account is NOT a manual booking field — only bank reconciliation
        # sets it (confirm_line passes ``account_id`` explicitly).
        account_name = await self._validate_account(account_id)
        expense = BudgetExpense(
            id=uuid.uuid4(),
            budget_id=node.id,
            fiscal_year_id=fy_id,
            application_id=payload.application_id,
            account_id=account_id,
            kind=payload.kind,
            amount=payload.amount,
            currency=node.currency,
            description=payload.description,
            actor=actor,
            invoice_date=payload.invoice_date,
            payment_date=payload.payment_date,
            correspondent=payload.correspondent,
            note=payload.note,
            reference_number=payload.reference_number,
            payment_method=payload.payment_method,
            category=payload.category,
            invoice_id=payload.invoice_id,
        )
        self.session.add(expense)
        await self._audit(
            AuditAction.BUDGET_EXPENSE_CREATE,
            target_type="budget_expense",
            target_id=str(expense.id),
            data={
                "budgetId": str(node.id),
                "fiscalYearId": str(fy_id),
                "kind": payload.kind,
                "amount": str(payload.amount),
                "applicationId": (str(payload.application_id) if payload.application_id else None),
            },
        )
        if payload.invoice_id is not None:
            await self._mark_invoice_paid(payload.invoice_id)
        # ``commit=False``: the caller bundles the booking with follow-up mutations
        # in ONE transaction (e.g. bank reconcile: claim + booking + allocation).
        if commit:
            await self.session.commit()
        names = await self._actor_names({expense.actor} if expense.actor else set())
        return self._expense_out(
            expense,
            node.path_key,
            app_title,
            account_name,
            actor_name=names.get(expense.actor or ""),
        )

    async def _validate_account(self, account_id: UUID | None) -> str | None:
        """Validate the account (if given) → its name; else ``None``."""
        if account_id is None:
            return None
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        return acc.name

    async def _mark_invoice_paid(self, invoice_id: UUID) -> None:
        """Set the linked invoice to ``paid`` on booking.

        Open → paid; already paid is a no-op. Unknown invoice → 404 (instead of
        failing on the FK at commit). No own commit — runs in the booking's
        transaction.
        """
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        if inv.status == "paid":
            return
        inv.status = "paid"
        await self._audit(
            AuditAction.BUDGET_INVOICE_UPDATE,
            target_type="invoice",
            target_id=str(inv.id),
            data={"status": "paid", "reason": "expense_booked"},
        )

    async def update_expense(self, expense_id: UUID, payload: ExpenseUpdate) -> ExpenseOut:
        """Update a booking: amount, description, bank account, cost centre and
        extra metadata. Fiscal year/application binding stay fixed. Only set
        fields are written; explicit ``null`` clears an optional field."""
        expense = await self.session.get(BudgetExpense, expense_id)
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        fields = payload.model_fields_set
        # Sub-booking invariant: never set the parent amount directly while
        # children exist (it equals the children sum). Count only when an amount
        # is actually being set (no extra query otherwise).
        child_n = 0
        if "amount" in fields and payload.amount is not None:
            child_n = (await self._child_counts([expense_id])).get(expense_id, 0)
            if child_n > 0:
                raise ValidationProblem(
                    "The amount of a booking with sub-bookings is the sum of its sub-bookings.",
                    code="subbooking_parent_amount_readonly",
                )
        if expense.parent_expense_id is not None and "budget_id" in fields:
            # Children inherit the cost centre from the parent — not movable alone.
            raise ValidationProblem(
                "A sub-booking inherits its cost-centre from its parent.",
                code="subbooking_inherited_field",
            )
        # Capture the prior values of the patched fields for audit-log revert.
        before: dict[str, object] = {f: _json_safe(getattr(expense, f)) for f in fields}
        if "amount" in fields and payload.amount is not None:
            expense.amount = payload.amount
        if "description" in fields and payload.description is not None:
            expense.description = payload.description
        if "budget_id" in fields and payload.budget_id is not None:
            # Re-book to another cost centre: target must exist (404 otherwise).
            # FY stays fixed; currency follows the new cost centre. ``budgetId``
            # is a required FK → ``null`` is a no-op.
            target = await self._get_node(payload.budget_id)
            # The kept FY must belong to the target's top-level budget — else the
            # moved booking would point at a foreign FY (orphan FY / phantom row
            # with allocated=0 and negative available). Mirrors book_expense /
            # move_fiscal_year: 422 on top-level mismatch.
            await self._resolve_fiscal_year(target, expense.fiscal_year_id)
            expense.budget_id = target.id
            expense.currency = target.currency
        if "invoice_date" in fields:
            expense.invoice_date = payload.invoice_date
        if "payment_date" in fields:
            expense.payment_date = payload.payment_date
        if "correspondent" in fields:
            expense.correspondent = payload.correspondent
        if "note" in fields:
            expense.note = payload.note
        if "reference_number" in fields:
            expense.reference_number = payload.reference_number
        if "payment_method" in fields:
            expense.payment_method = payload.payment_method
        if "category" in fields:
            expense.category = payload.category
        if "invoice_id" in fields:
            expense.invoice_id = payload.invoice_id
            if payload.invoice_id is not None:
                await self._mark_invoice_paid(payload.invoice_id)
        # Capture the new values too: revert uses them to detect later edits
        # (stale → 409 instead of overwriting someone else's changes).
        after: dict[str, object] = {f: _json_safe(getattr(expense, f)) for f in fields}
        await self._audit(
            AuditAction.BUDGET_EXPENSE_UPDATE,
            target_type="budget_expense",
            target_id=str(expense.id),
            data={
                "fields": sorted(fields),
                "amount": str(expense.amount),
                "before": before,
                "after": after,
            },
        )
        # Child amount changed → recompute parent amount = children sum.
        if expense.parent_expense_id is not None and "amount" in fields:
            await self.session.flush()
            await self._recompute_parent_amount(expense.parent_expense_id)
        await self.session.commit()
        node = await self._get_node(expense.budget_id)
        app_title: str | None = None
        if expense.application_id is not None:
            app = await self.session.get(Application, expense.application_id)
            app_title = _title_of(app.data) if app is not None else None
        # Defensive: a parallel ``delete_account`` (FK SET NULL) can remove the
        # account row between booking and re-read → ``get`` returns None.
        acc = (
            await self.session.get(Account, expense.account_id)
            if expense.account_id is not None
            else None
        )
        acc_name = acc.name if acc is not None else None
        names = await self._actor_names({expense.actor} if expense.actor else set())
        return self._expense_out(
            expense,
            node.path_key,
            app_title,
            acc_name,
            actor_name=names.get(expense.actor or ""),
            child_count=child_n,
        )

    async def list_expenses(
        self, budget_id: UUID, fiscal_year_id: UUID | None = None
    ) -> list[ExpenseOut]:
        """(Compat) Bookings of this cost centre + subtree (optional FY filter)."""
        page = await self.list_expenses_paged(
            budget_id=budget_id, fiscal_year_id=fiscal_year_id, limit=10_000, offset=0
        )
        return page.items

    async def list_expenses_paged(
        self,
        *,
        expense_id: UUID | None = None,
        budget_id: UUID | None = None,
        fiscal_year_id: UUID | None = None,
        account_id: UUID | None = None,
        kind: str | None = None,
        application_id: UUID | None = None,
        unallocated: bool = False,
        q: str | None = None,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ExpenseOut]:
        """Bookings (expenses/income) filtered + offset-paginated.

        ``budget_id`` restricts to the cost centre **and its subtree**.
        """
        # List only top-level bookings — sub-bookings show up when expanding the
        # parent booking, not as own rows (and not as link candidates).
        filters: list[ColumnElement[bool]] = [BudgetExpense.parent_expense_id.is_(None)]
        if expense_id is not None:
            # Exact-booking deep link (Konten "view booking", #expenses-ux).
            filters.append(BudgetExpense.id == expense_id)
        if budget_id is not None:
            node = await self._get_node(budget_id)
            subtree = select(Budget.id).where(
                or_(
                    Budget.path_key == node.path_key,
                    Budget.path_key.like(node.path_key + _SEP + "%"),
                )
            )
            filters.append(BudgetExpense.budget_id.in_(subtree))
        if fiscal_year_id is not None:
            filters.append(BudgetExpense.fiscal_year_id == fiscal_year_id)
        if account_id is not None:
            filters.append(BudgetExpense.account_id == account_id)
        if kind is not None:
            filters.append(BudgetExpense.kind == kind)
        if unallocated:
            # Only bookings WITHOUT a bank allocation (link candidates).
            filters.append(
                ~exists().where(BankAllocation.expense_id == BudgetExpense.id)
            )
        if application_id is not None:
            filters.append(BudgetExpense.application_id == application_id)
        # Fuzzy search: trigram ranking over the booking's free-text fields plus
        # joined texts (application/account/invoice). ``rank_expr`` orders the
        # hits; ``where`` goes into the SHARED ``filters`` (count and row query
        # stay identical).
        rank_expr = None
        if q and q.strip():
            where, rank_expr = trigram_rank(
                q,
                [
                    BudgetExpense.description,
                    BudgetExpense.correspondent,
                    BudgetExpense.reference_number,
                    BudgetExpense.category,
                    BudgetExpense.note,
                    Invoice.number,
                    Invoice.supplier,
                    Account.name,
                    func.cast(Application.data, _Text),
                ],
                dialect=dialect_of(self.session),
            )
            filters.append(where)
        if amount_min is not None:
            filters.append(BudgetExpense.amount >= amount_min)
        if amount_max is not None:
            filters.append(BudgetExpense.amount <= amount_max)
        if created_from:
            filters.append(func.date(BudgetExpense.created_at) >= created_from)
        if created_to:
            filters.append(func.date(BudgetExpense.created_at) <= created_to)

        # Sort column (whitelist) + direction; default: newest first.
        sort_map = {
            "amount": BudgetExpense.amount,
            "invoiceDate": BudgetExpense.invoice_date,
            "paymentDate": BudgetExpense.payment_date,
        }
        sort_col = sort_map.get(sort or "", BudgetExpense.created_at)
        direction = sort_col.asc() if order == "asc" else sort_col.desc()
        # Nullable date columns: empty values go last regardless of direction.
        ordering = direction.nulls_last() if sort in ("invoiceDate", "paymentDate") else direction

        # The search references joined texts (application/account/invoice) → the
        # count query must carry the same joins as the row query, otherwise the
        # ``where`` over foreign tables does not resolve (or cross-joins).
        # Without ``q`` the count query stays lean (no join).
        count_stmt = select(func.count()).select_from(BudgetExpense)
        if rank_expr is not None:
            count_stmt = (
                count_stmt.outerjoin(Application, Application.id == BudgetExpense.application_id)
                .outerjoin(Account, Account.id == BudgetExpense.account_id)
                .outerjoin(Invoice, Invoice.id == BudgetExpense.invoice_id)
            )
        total = await self.session.scalar(count_stmt.where(*filters))
        # Search active ⇒ most relevant first (rank), then the previous ordering
        # as deterministic tiebreak; unchanged without search.
        order_by = (
            (rank_expr.desc(), ordering, BudgetExpense.created_at.desc())
            if rank_expr is not None
            else (ordering, BudgetExpense.created_at.desc())
        )
        rows = (
            await self.session.execute(
                select(
                    BudgetExpense,
                    Budget.path_key,
                    Application.data,
                    Account.name,
                    Invoice.number,
                )
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .outerjoin(Application, Application.id == BudgetExpense.application_id)
                .outerjoin(Account, Account.id == BudgetExpense.account_id)
                .outerjoin(Invoice, Invoice.id == BudgetExpense.invoice_id)
                .where(*filters)
                .order_by(*order_by)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        # Collect actor UUIDs → display names in one query.
        names = await self._actor_names({row[0].actor for row in rows if row[0].actor})
        # Sub-booking count per row in ONE grouped query.
        child_counts = await self._child_counts([row[0].id for row in rows])
        items = [
            self._expense_out(
                e,
                path_key,
                _title_of(data) if data else None,
                acc_name,
                inv_number,
                actor_name=names.get(e.actor or ""),
                child_count=child_counts.get(e.id, 0),
            )
            for (e, path_key, data, acc_name, inv_number) in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def _child_counts(self, parent_ids: list[UUID]) -> dict[UUID, int]:
        """Sub-booking count per parent id — one grouped query."""
        if not parent_ids:
            return {}
        rows = (
            await self.session.execute(
                select(BudgetExpense.parent_expense_id, func.count())
                .where(BudgetExpense.parent_expense_id.in_(parent_ids))
                .group_by(BudgetExpense.parent_expense_id)
            )
        ).all()
        return {pid: n for pid, n in rows if pid is not None}

    async def delete_expense(self, expense_id: UUID) -> None:
        """Delete a booking. Part of a transfer → delete both paired bookings."""
        expense = (
            await self.session.execute(select(BudgetExpense).where(BudgetExpense.id == expense_id))
        ).scalar_one_or_none()
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        await self._audit(
            AuditAction.BUDGET_EXPENSE_DELETE,
            target_type="budget_expense",
            target_id=str(expense_id),
            data={
                "budgetId": str(expense.budget_id),
                "kind": expense.kind,
                "amount": str(expense.amount),
                "priorActor": expense.actor,
                "transferId": str(expense.transfer_id) if expense.transfer_id else None,
            },
        )
        parent_id = expense.parent_expense_id
        if expense.transfer_id is not None:
            pair = (
                (
                    await self.session.execute(
                        select(BudgetExpense).where(
                            BudgetExpense.transfer_id == expense.transfer_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for e in pair:
                await self.session.delete(e)
        else:
            await self.session.delete(expense)
        # Sub-booking deleted → parent amount = sum of the remaining children.
        if parent_id is not None:
            await self.session.flush()
            await self._recompute_parent_amount(parent_id)
        await self.session.commit()

    async def _recompute_parent_amount(self, parent_id: UUID) -> None:
        """Parent amount = sum of sub-bookings. If the parent has NO children
        left, its ``amount`` stays unchanged (it becomes a standalone booking
        again — ``amount`` > 0 stays satisfied)."""
        total = await self.session.scalar(
            select(func.coalesce(func.sum(BudgetExpense.amount), 0)).where(
                BudgetExpense.parent_expense_id == parent_id
            )
        )
        if total and Decimal(total) > 0:
            parent = await self.session.get(BudgetExpense, parent_id)
            if parent is not None:
                parent.amount = Decimal(total)
