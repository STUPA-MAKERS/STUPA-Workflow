"""Expense and income bookings: create, update, filtered list and delete."""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy import Text as _Text

from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.audit.actions import AuditAction
from app.modules.budget.tree.service_base import BudgetTreeServiceBase, _json_safe
from app.modules.budget.tree_models import (
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
    """Book, update, list and delete expense and income bookings."""

    async def _actor_names(self, subs: set[str]) -> dict[str, str]:
        """Map every booking actor (principal `sub`) to a display name.

        The actor UUID must never reach the UI. An old actor value that already
        holds a name matches no principal and stays out of the map. The frontend
        then falls back to `actor`.

        Returns:
            The display name per `sub`. The name falls back to the email, then
            to the `sub` itself.
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
        """Book against the cost center from the path `/budgets/{id}`.

        Kept for compatibility with the older route.
        """
        return await self.book_expense(
            payload.model_copy(update={"budget_id": budget_id}), actor=actor
        )

    async def book_expense(
        self,
        payload: ExpenseCreate,
        *,
        actor: str,
        commit: bool = True,
    ) -> ExpenseOut:
        """Book an expense or an income.

        A booking with `applicationId` set inherits the cost center and the
        fiscal year from the application. A standalone booking needs `budgetId`.
        The service then resolves the fiscal year itself.
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
        expense = BudgetExpense(
            id=uuid.uuid4(),
            budget_id=node.id,
            fiscal_year_id=fy_id,
            application_id=payload.application_id,
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
        # With commit=False the caller bundles the booking and its follow-up
        # mutations in one transaction.
        if commit:
            await self.session.commit()
        names = await self._actor_names({expense.actor} if expense.actor else set())
        return self._expense_out(
            expense,
            node.path_key,
            app_title,
            actor_name=names.get(expense.actor or ""),
        )

    async def _mark_invoice_paid(self, invoice_id: UUID) -> None:
        """Set the linked invoice to `paid` when a booking references it.

        An invoice that is already paid stays unchanged. The method does not
        commit. It runs inside the transaction of the booking.

        Raises:
            NotFoundError: The invoice does not exist. The check happens here so
                the request fails with 404 instead of on the foreign key at
                commit time.
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
        """Update a booking.

        The caller can change the amount, the description, the cost center and
        the extra metadata. The fiscal year and the application binding stay
        fixed. The service writes only the fields that the payload
        sets. An explicit `null` clears an optional field.
        """
        expense = await self.session.get(BudgetExpense, expense_id)
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        fields = payload.model_fields_set
        # Sub-booking invariant: never set the parent amount directly while
        # children exist. It equals the sum of the children. Count the children
        # only when the payload sets an amount, to save one query.
        child_n = 0
        if "amount" in fields and payload.amount is not None:
            child_n = (await self._child_counts([expense_id])).get(expense_id, 0)
            if child_n > 0:
                raise ValidationProblem(
                    "The amount of a booking with sub-bookings is the sum of its sub-bookings.",
                    code="subbooking_parent_amount_readonly",
                )
        if expense.parent_expense_id is not None and "budget_id" in fields:
            # A child inherits the cost center from its parent. It cannot move alone.
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
            # Re-book to another cost center. The target must exist, else 404.
            # The fiscal year stays fixed. The currency follows the new cost
            # center. budgetId is a required FK, so null does nothing.
            target = await self._get_node(payload.budget_id)
            # The kept fiscal year must belong to the top-level budget of the
            # target. Otherwise the moved booking points at a foreign fiscal
            # year: an orphan year, or a phantom row with allocated=0 and a
            # negative available sum. This mirrors book_expense and
            # move_fiscal_year: 422 on a top-level mismatch.
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
        # Capture the new values too. Revert uses them to detect a later edit
        # and answers 409 instead of overwriting the changes of another user.
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
        if expense.parent_expense_id is not None and "amount" in fields:
            await self.session.flush()
            await self._recompute_parent_amount(expense.parent_expense_id)
        await self.session.commit()
        node = await self._get_node(expense.budget_id)
        app_title: str | None = None
        if expense.application_id is not None:
            app = await self.session.get(Application, expense.application_id)
            app_title = _title_of(app.data) if app is not None else None
        names = await self._actor_names({expense.actor} if expense.actor else set())
        return self._expense_out(
            expense,
            node.path_key,
            app_title,
            actor_name=names.get(expense.actor or ""),
            child_count=child_n,
        )

    async def list_expenses(
        self, budget_id: UUID, fiscal_year_id: UUID | None = None
    ) -> list[ExpenseOut]:
        """List the bookings of this cost center and of its subtree.

        Kept for compatibility. The fiscal year filter is optional.
        """
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
        kind: str | None = None,
        application_id: UUID | None = None,
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
        """List bookings, that is expenses and income, filtered and paginated.

        `budget_id` restricts the result to this cost center and its subtree.
        """
        # List only top-level bookings. A sub-booking appears when the user
        # expands its parent. It is no row of its own and no link candidate.
        filters: list[ColumnElement[bool]] = [BudgetExpense.parent_expense_id.is_(None)]
        if expense_id is not None:
            # Deep link to one exact booking.
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
        if kind is not None:
            filters.append(BudgetExpense.kind == kind)
        if application_id is not None:
            filters.append(BudgetExpense.application_id == application_id)
        # Fuzzy search: a trigram rank over the free-text fields of the booking
        # plus the joined texts of application and invoice. rank_expr
        # orders the hits. The where clause goes into the shared filters list,
        # so the count query and the row query stay identical.
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

        # Sort column (whitelist) and direction. The default is newest first.
        sort_map = {
            "amount": BudgetExpense.amount,
            "invoiceDate": BudgetExpense.invoice_date,
            "paymentDate": BudgetExpense.payment_date,
        }
        sort_col = sort_map.get(sort or "", BudgetExpense.created_at)
        direction = sort_col.asc() if order == "asc" else sort_col.desc()
        # Nullable date columns: empty values go last regardless of direction.
        ordering = direction.nulls_last() if sort in ("invoiceDate", "paymentDate") else direction

        # The search reads joined texts from application and invoice. The count
        # query must carry the same joins as the row query. Otherwise the where
        # clause over the foreign tables does not resolve, or it cross-joins.
        # Without q the count query stays lean and adds no join.
        count_stmt = select(func.count()).select_from(BudgetExpense)
        if rank_expr is not None:
            count_stmt = count_stmt.outerjoin(
                Application, Application.id == BudgetExpense.application_id
            ).outerjoin(Invoice, Invoice.id == BudgetExpense.invoice_id)
        total = await self.session.scalar(count_stmt.where(*filters))
        # With an active search the most relevant hit comes first. The normal
        # ordering then acts as a deterministic tiebreak. Without a search
        # nothing changes.
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
                    Invoice.number,
                )
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .outerjoin(Application, Application.id == BudgetExpense.application_id)
                .outerjoin(Invoice, Invoice.id == BudgetExpense.invoice_id)
                .where(*filters)
                .order_by(*order_by)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        names = await self._actor_names({row[0].actor for row in rows if row[0].actor})
        child_counts = await self._child_counts([row[0].id for row in rows])
        items = [
            self._expense_out(
                e,
                path_key,
                _title_of(data) if data else None,
                inv_number,
                actor_name=names.get(e.actor or ""),
                child_count=child_counts.get(e.id, 0),
            )
            for (e, path_key, data, inv_number) in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def _child_counts(self, parent_ids: list[UUID]) -> dict[UUID, int]:
        """Count the sub-bookings per parent id with one grouped query."""
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
        """Delete a booking.

        If the booking belongs to a transfer, delete both paired bookings.
        """
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
        if parent_id is not None:
            await self.session.flush()
            await self._recompute_parent_amount(parent_id)
        await self.session.commit()

    async def _recompute_parent_amount(self, parent_id: UUID) -> None:
        """Set the parent amount to the sum of its sub-bookings.

        If no child is left, the `amount` of the parent stays unchanged. The
        parent becomes a standalone booking again and keeps `amount` > 0.
        """
        total = await self.session.scalar(
            select(func.coalesce(func.sum(BudgetExpense.amount), 0)).where(
                BudgetExpense.parent_expense_id == parent_id
            )
        )
        if total and Decimal(total) > 0:
            parent = await self.session.get(BudgetExpense, parent_id)
            if parent is not None:
                parent.amount = Decimal(total)
