"""Filtered, paginated list of staged statement lines (plus the raw detail view)."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select

from app.modules.budget.bank.service_base import BankServiceBase
from app.modules.budget.tree_models import BankAllocation, BankStatementLine
from app.modules.budget.tree_schemas import StatementLineDetail, StatementLineOut
from app.shared.errors import NotFoundError
from app.shared.paging import Page


class ListingOps(BankServiceBase):
    """Read path of the staged statement lines."""

    async def list_lines_paged(
        self,
        *,
        account_id: uuid.UUID | None,
        state: str | None,
        linked: bool | None = None,
        include_ignored: bool = True,
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

        The filters are ``account``, ``state``, ``kind`` and a date range. ``kind``
        selects income (amount > 0) or expense (amount < 0). The date range applies
        to the value date, or to the booking date when no value date exists. ``q``
        is a full-text term over counterparty, IBAN and purpose. ``sort`` accepts
        ``date`` (default) or ``amount``.
        """
        filters = []
        if account_id is not None:
            filters.append(BankStatementLine.account_id == account_id)
        if state is not None:
            filters.append(BankStatementLine.match_state == state)
        elif not include_ignored:
            # "All" view: show matched and open lines, but hide the set-aside ones.
            filters.append(BankStatementLine.match_state != "ignored")
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
            # Escape the LIKE metacharacters. A literal "%" or "_" in the search
            # term must not act as a wildcard.
            term = (
                q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            like = f"%{term}%"
            filters.append(
                or_(
                    BankStatementLine.counterparty_name.ilike(like, escape="\\"),
                    BankStatementLine.counterparty_iban.ilike(like, escape="\\"),
                    BankStatementLine.purpose.ilike(like, escape="\\"),
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
        matched = await self._matched_expense_ids(
            [r.id for r in rows if r.match_state == "matched"]
        )
        items = [
            self._line_out(
                r,
                paths.get(r.suggested_budget_id) if r.suggested_budget_id else None,
                matched_expense_id=matched.get(r.id),
            )
            for r in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def get_line(self, line_id: uuid.UUID) -> StatementLineDetail:
        """Return one staged line with its raw payload and idempotency key.

        This is a diagnostic view. It answers questions such as "which source
        format staged this batch line?". The read permissions are the same as for
        the list. The raw payload is bank data that the caller can already see
        through the list or the export.
        """
        line = await self.session.get(BankStatementLine, line_id)
        if line is None:
            raise NotFoundError(f"statement line {line_id} not found")
        paths = await self._path_keys(
            {line.suggested_budget_id} if line.suggested_budget_id else set()
        )
        matched = await self._matched_expense_ids(
            [line.id] if line.match_state == "matched" else []
        )
        base = self._line_out(
            line,
            paths.get(line.suggested_budget_id) if line.suggested_budget_id else None,
            matched_expense_id=matched.get(line.id),
        )
        return StatementLineDetail(
            **base.model_dump(by_alias=True),
            rawPayload=dict(line.raw_payload or {}),
            idempotencyKey=line.idempotency_key,
        )

    async def _matched_expense_ids(
        self, line_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Map every matched line to its booking from ``bank_allocation``.

        A split payment has several allocations. The oldest allocation wins as the
        deep-link target.
        """
        if not line_ids:
            return {}
        rows = (
            await self.session.execute(
                select(BankAllocation.statement_line_id, BankAllocation.expense_id)
                .where(BankAllocation.statement_line_id.in_(line_ids))
                .order_by(BankAllocation.created_at.asc())
            )
        ).all()
        out: dict[uuid.UUID, uuid.UUID] = {}
        for line_id, expense_id in rows:
            out.setdefault(line_id, expense_id)
        return out
