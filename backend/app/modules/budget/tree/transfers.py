"""Transfers between cost centers as a paired expense and income booking.

A transfer is two `budget_expense` rows joined by `transfer_id`: an expense on
the source and an income on the target. The read, the update and the delete all
treat that pair as ONE entity, so the two legs never drift apart.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import aliased

from app.modules.audit.actions import AuditAction
from app.modules.budget import tree_rules
from app.modules.budget.tree.expenses import ExpenseOps
from app.modules.budget.tree.service_base import _json_safe
from app.modules.budget.tree_models import Budget, BudgetExpense
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import (
    TransferCreate,
    TransferOut,
    TransferRowOut,
    TransferUpdate,
)
from app.search import dialect_of, trigram_rank
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from app.shared.paging import Page

# The fields a transfer patch may write. Both legs get the same value.
_PATCHABLE: tuple[str, ...] = (
    "amount",
    "description",
    "note",
    "invoice_date",
    "payment_date",
)


class TransferOps(ExpenseOps):
    """Create, read, update and delete transfers as one entity."""

    async def create_transfer(self, payload: TransferCreate, *, actor: str) -> TransferOut:
        """Transfer between two cost centers.

        The service books an expense on the source and an income on the target.
        Both bookings use the same fiscal year.
        """
        src = await self._get_node(payload.from_budget_id)
        dst = await self._get_node(payload.to_budget_id)
        # The fiscal year must belong to the top level of both cost centers.
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

    async def _legs(self, transfer_id: UUID) -> tuple[BudgetExpense, BudgetExpense]:
        """Load the source expense and the target income of one transfer.

        Raises:
            NotFoundError: No transfer has this id, or one leg is missing (404).
                A half transfer is unreachable through this entity. The single
                booking is still visible and removable under `/budget-expenses`.
        """
        rows = (
            (
                await self.session.execute(
                    select(BudgetExpense).where(BudgetExpense.transfer_id == transfer_id)
                )
            )
            .scalars()
            .all()
        )
        out = next((r for r in rows if r.kind == "expense"), None)
        income = next((r for r in rows if r.kind == "income"), None)
        if out is None or income is None:
            raise NotFoundError(f"budget transfer {transfer_id} not found")
        return out, income

    async def _path_keys(self, budget_ids: set[UUID]) -> dict[UUID, str]:
        """Map every cost-center id to its `path_key` with one query."""
        if not budget_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Budget.id, Budget.path_key).where(Budget.id.in_(budget_ids))
            )
        ).all()
        return {bid: path for bid, path in rows}

    @staticmethod
    def _row_out(
        out: BudgetExpense,
        income: BudgetExpense,
        paths: dict[UUID, str],
        actor_name: str | None = None,
    ) -> TransferRowOut:
        return TransferRowOut(
            transferId=out.transfer_id,  # pyright: ignore[reportArgumentType] - both legs carry it
            expenseId=out.id,
            incomeId=income.id,
            fromBudgetId=out.budget_id,
            fromPathKey=paths.get(out.budget_id),
            toBudgetId=income.budget_id,
            toPathKey=paths.get(income.budget_id),
            fiscalYearId=out.fiscal_year_id,
            amount=out.amount,
            currency=out.currency,
            description=out.description,
            note=out.note,
            invoiceDate=out.invoice_date,
            paymentDate=out.payment_date,
            actor=out.actor,
            actorName=actor_name,
            createdAt=out.created_at,
        )

    async def list_transfers_paged(
        self,
        *,
        transfer_id: UUID | None = None,
        budget_id: UUID | None = None,
        fiscal_year_id: UUID | None = None,
        q: str | None = None,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[TransferRowOut]:
        """List transfers, filtered and paginated, in the style of `GET /expenses`.

        The source expense anchors the query, so every transfer appears exactly
        once. `budget_id` matches EITHER cost centre and includes the subtree,
        because a transfer is interesting from both ends. `q` searches the
        description and the note.
        """
        filters: list[ColumnElement[bool]] = [
            BudgetExpense.transfer_id.is_not(None),
            BudgetExpense.kind == "expense",
        ]
        if transfer_id is not None:
            filters.append(BudgetExpense.transfer_id == transfer_id)
        if budget_id is not None:
            node = await self._get_node(budget_id)
            subtree = select(Budget.id).where(
                or_(
                    Budget.path_key == node.path_key,
                    Budget.path_key.like(node.path_key + _SEP + "%"),
                )
            )
            # Either leg may sit in the subtree, so match through the transfer id.
            leg = aliased(BudgetExpense)
            filters.append(
                BudgetExpense.transfer_id.in_(
                    select(leg.transfer_id).where(leg.budget_id.in_(subtree))
                )
            )
        if fiscal_year_id is not None:
            filters.append(BudgetExpense.fiscal_year_id == fiscal_year_id)
        rank_expr = None
        if q and q.strip():
            where, rank_expr = trigram_rank(
                q,
                [BudgetExpense.description, BudgetExpense.note],
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

        sort_map = {
            "amount": BudgetExpense.amount,
            "invoiceDate": BudgetExpense.invoice_date,
            "paymentDate": BudgetExpense.payment_date,
        }
        sort_col = sort_map.get(sort or "", BudgetExpense.created_at)
        direction = sort_col.asc() if order == "asc" else sort_col.desc()
        ordering = direction.nulls_last() if sort in ("invoiceDate", "paymentDate") else direction
        order_by = (
            (rank_expr.desc(), ordering, BudgetExpense.created_at.desc())
            if rank_expr is not None
            else (ordering, BudgetExpense.created_at.desc())
        )

        total = await self.session.scalar(
            select(func.count()).select_from(BudgetExpense).where(*filters)
        )
        out_rows = list(
            (
                await self.session.execute(
                    select(BudgetExpense)
                    .where(*filters)
                    .order_by(*order_by)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return Page(
            items=await self._assemble_rows(out_rows),
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    async def _assemble_rows(self, out_rows: list[BudgetExpense]) -> list[TransferRowOut]:
        """Join every source leg with its income leg, its path keys and its actor name."""
        if not out_rows:
            return []
        transfer_ids = [r.transfer_id for r in out_rows if r.transfer_id is not None]
        incomes = {
            r.transfer_id: r
            for r in (
                (
                    await self.session.execute(
                        select(BudgetExpense).where(
                            BudgetExpense.transfer_id.in_(transfer_ids),
                            BudgetExpense.kind == "income",
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        pairs = [(r, incomes[r.transfer_id]) for r in out_rows if r.transfer_id in incomes]
        paths = await self._path_keys(
            {r.budget_id for pair in pairs for r in pair}
        )
        names = await self._actor_names({r.actor for r, _ in pairs if r.actor})
        return [
            self._row_out(out, income, paths, actor_name=names.get(out.actor or ""))
            for out, income in pairs
        ]

    async def get_transfer(self, transfer_id: UUID) -> TransferRowOut:
        """Read one transfer as a single row."""
        out, income = await self._legs(transfer_id)
        paths = await self._path_keys({out.budget_id, income.budget_id})
        names = await self._actor_names({out.actor} if out.actor else set())
        return self._row_out(out, income, paths, actor_name=names.get(out.actor or ""))

    async def update_transfer(
        self, transfer_id: UUID, payload: TransferUpdate
    ) -> TransferRowOut:
        """Patch both legs of a transfer in one transaction.

        The amount, the description, the note and the two business dates apply
        to the source expense and to the target income together, so the pair
        never drifts. The cost centres and the fiscal year stay fixed.

        The audit entry uses the existing `budget_expense_update` action with
        `target_type='budget_transfer'`, the same shape that the transfer
        revert already writes. It records the prior values under `prior`
        instead of `before` ON PURPOSE: the audit revert restores exactly one
        `budget_expense` row, and a one-sided revert would desync the pair.
        `AuditService.revertable_flags` therefore reports the entry as not
        revertable, and the operator deletes and re-books instead.

        Raises:
            NotFoundError: No transfer has this id (404).
            ConflictError: The patch asks for a different pair of cost centres
                (409).
        """
        out, income = await self._legs(transfer_id)
        if tree_rules.transfer_pair_changed(
            out.budget_id, income.budget_id, payload.from_budget_id, payload.to_budget_id
        ):
            raise ConflictError(
                "The cost centres of a transfer are immutable; book a new transfer instead.",
                code="transfer_cost_centres_immutable",
            )
        fields = [f for f in _PATCHABLE if f in payload.model_fields_set]
        prior = {f: _json_safe(getattr(out, f)) for f in fields}
        for field in fields:
            value = getattr(payload, field)
            setattr(out, field, value)
            setattr(income, field, value)
        current = {f: _json_safe(getattr(out, f)) for f in fields}
        await self._audit(
            AuditAction.BUDGET_EXPENSE_UPDATE,
            target_type="budget_transfer",
            target_id=str(transfer_id),
            data={
                "fields": sorted(fields),
                "expenseId": str(out.id),
                "incomeId": str(income.id),
                "prior": prior,
                "current": current,
            },
        )
        await self.session.commit()
        paths = await self._path_keys({out.budget_id, income.budget_id})
        names = await self._actor_names({out.actor} if out.actor else set())
        return self._row_out(out, income, paths, actor_name=names.get(out.actor or ""))

    async def delete_transfer(self, transfer_id: UUID) -> None:
        """Delete both legs of a transfer.

        `DELETE /budget-expenses/{id}` on a single leg already removes the pair.
        This route is the entity-level path and does the same thing from the
        transfer id. The audit entry reuses `budget_expense_delete` with
        `target_type='budget_transfer'`, exactly like the transfer revert.

        Raises:
            NotFoundError: No transfer has this id (404).
        """
        out, income = await self._legs(transfer_id)
        await self._audit(
            AuditAction.BUDGET_EXPENSE_DELETE,
            target_type="budget_transfer",
            target_id=str(transfer_id),
            data={
                "fromBudgetId": str(out.budget_id),
                "toBudgetId": str(income.budget_id),
                "fiscalYearId": str(out.fiscal_year_id),
                "amount": str(out.amount),
                "priorActor": out.actor,
            },
        )
        await self.session.delete(out)
        await self.session.delete(income)
        await self.session.commit()
