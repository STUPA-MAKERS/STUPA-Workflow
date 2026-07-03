"""Filtered, paginated list of staged statement lines."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select

from app.modules.budget.bank.service_base import BankServiceBase
from app.modules.budget.tree_models import BankStatementLine
from app.modules.budget.tree_schemas import StatementLineOut
from app.shared.paging import Page


class ListingOps(BankServiceBase):
    """Read path of the staged statement lines."""

    async def list_lines_paged(
        self,
        *,
        account_id: uuid.UUID | None,
        state: str | None,
        linked: bool | None = None,
        kind: str | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[StatementLineOut]:
        """List staged lines, filtered and offset-paginated.

        Filters: ``account``, ``state``, ``kind`` (income = amount > 0, expense < 0),
        date range (value date, else booking date) and full text (``q``) over
        counterparty/IBAN/purpose. ``sort`` = ``date`` (default) | ``amount``."""
        filters = []
        if account_id is not None:
            filters.append(BankStatementLine.account_id == account_id)
        if state is not None:
            filters.append(BankStatementLine.match_state == state)
        if linked is True:
            filters.append(BankStatementLine.match_state == "matched")
        elif linked is False:
            # "open" = not yet booked (unmatched/suggested), excluding ignored lines.
            filters.append(BankStatementLine.match_state.in_(("unmatched", "suggested")))
        if kind == "income":
            filters.append(BankStatementLine.amount > 0)
        elif kind == "expense":
            filters.append(BankStatementLine.amount < 0)
        eff_date = func.coalesce(BankStatementLine.value_date, BankStatementLine.booking_date)
        if date_from:
            filters.append(eff_date >= date_from)
        if date_to:
            filters.append(eff_date <= date_to)
        if q and q.strip():
            like = f"%{q.strip()}%"
            filters.append(
                or_(
                    BankStatementLine.counterparty_name.ilike(like),
                    BankStatementLine.counterparty_iban.ilike(like),
                    BankStatementLine.purpose.ilike(like),
                )
            )
        where = and_(*filters) if filters else None
        count_stmt = select(func.count()).select_from(BankStatementLine)
        if where is not None:
            count_stmt = count_stmt.where(where)
        total = await self.session.scalar(count_stmt)
        if sort == "amount":
            primary = (
                BankStatementLine.amount.asc()
                if order == "asc"
                else BankStatementLine.amount.desc()
            )
        else:
            primary = eff_date.asc().nullslast() if order == "asc" else eff_date.desc().nullslast()
        stmt = select(BankStatementLine)
        if where is not None:
            stmt = stmt.where(where)
        stmt = (
            stmt.order_by(primary, BankStatementLine.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.scalars(stmt)).all()
        paths = await self._path_keys(
            {r.suggested_budget_id for r in rows if r.suggested_budget_id}
        )
        items = [
            self._line_out(
                r, paths.get(r.suggested_budget_id) if r.suggested_budget_id else None
            )
            for r in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)
