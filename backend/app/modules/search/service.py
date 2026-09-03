"""Fan-out search across the record kinds a principal may see.

The service owns NO authorization of its own. Every source calls the listing that
already serves that module's own endpoint, with the same scoping arguments its router
computes, so a hit can only appear here if the caller could have reached it through the
module's list. Adding a source therefore means wiring an existing gate, never writing a
new one — and a permission change in a module reaches the palette for free.

The two sources that had no list search yet (cost centres and Gremien) get their filter
here, together with the scope their module's router applies to reads.

Each source is capped and each source is isolated: one that raises is reported in
``failed`` and the rest still answer. A palette that shows four kinds beats one that
shows a stack trace.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.access import READ_ALL_PERMISSION, READ_PERMISSION
from app.modules.budget.tree_models import Budget
from app.modules.search.schemas import SearchHit, SearchKind, SearchResults
from app.search import dialect_of, trigram_rank
from app.shared.i18n import resolve_i18n

if TYPE_CHECKING:
    from app.modules.auth.principal import Principal

log = logging.getLogger(__name__)

#: Hits per kind. Small on purpose: a palette is a way to jump to one thing, not a
#: report. The client says so when a source hits the cap.
PER_KIND = 5

#: Below this the query matches too much to be useful and every source scans.
MIN_QUERY_LENGTH = 2

#: Where a hit of each kind sends the reader.
#:
#: Every template names the record: a path segment where the record has a page of its
#: own, and a filter the list applies where it does not. A bare list URL would drop the
#: reader back into the search they just ran.
#:
#: One table rather than seven f-strings scattered through the sources, so a new kind
#: cannot ship a URL that forgets which record it is about.
HIT_URL: Mapping[SearchKind, str] = {
    "application": "/applications/{id}",
    "meeting": "/meetings/{id}",
    "invoice": "/invoices?id={id}",
    "expense": "/expenses?id={id}",
    "budget": "/budget?ks={id}",
    "gremium": "/admin/gremien/{id}/members",
    # `sub` and not the row id: it is what the principal search matches on.
    "principal": "/admin/users?q={id}",
}


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, q: str, principal: Principal, *, lang: str = "de") -> SearchResults:
        """Search every source the principal may read.

        Returns an empty result for a query that is too short rather than an error: the
        palette calls this on every keystroke, and the first keystroke is not a mistake.

        A hit is one flat line, so an i18n label has to be resolved here rather than left
        for the client the way a list item leaves it. `lang` decides which translation.
        """
        query = q.strip()
        if len(query) < MIN_QUERY_LENGTH:
            return SearchResults(hits=[])

        sources = {
            "application": self._applications,
            "meeting": self._meetings,
            "invoice": self._invoices,
            "expense": self._expenses,
            "budget": self._budgets,
            "gremium": self._gremien,
            "principal": self._principals,
        }
        # Sequential, not gathered: they share one AsyncSession, and a session is not
        # safe for concurrent use. Each query is small and indexed.
        hits: list[SearchHit] = []
        failed: list[str] = []
        truncated = False
        for name, run in sources.items():
            try:
                found = await run(query, principal, lang)
            except Exception:  # noqa: BLE001 - one broken source must not empty the palette
                log.exception("search source %s failed", name)
                failed.append(name)
                continue
            if len(found) > PER_KIND:
                truncated = True
                found = found[:PER_KIND]
            hits.extend(found)
        return SearchResults(hits=hits, truncated=truncated, failed=failed)

    # -- sources ----------------------------------------------------------------
    #
    # Each one asks its own module. The comment on a source says which gate it reuses,
    # so a reader can check the claim without following the call.

    async def _applications(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Reuses `ApplicationsService.list_applications`, gated exactly as its router.

        A principal without a global read sees only their own applications plus the
        committee read scope, which the service resolves from the Gremium memberships.
        """
        from app.modules.applications.service import ApplicationsService

        can_read = principal.has(READ_PERMISSION) or principal.has(READ_ALL_PERMISSION)
        page = await ApplicationsService(self.session).list_applications(
            q=q,
            owner_sub=None if can_read else principal.sub,
            committee_sub=None if can_read else principal.sub,
            limit=PER_KIND + 1,
            offset=0,
        )
        return [
            SearchHit(
                kind="application",
                id=str(item.id),
                title=item.title or str(item.id),
                subtitle=(
                    resolve_i18n(item.state.label, lang, "de") if item.state is not None else None
                ),
                url=HIT_URL["application"].format(id=item.id),
            )
            for item in page.items
        ]

    async def _meetings(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Reuses `MeetingService.list_timeline`, which scopes to the visible Gremien."""
        from app.modules.livevote.service import MeetingService

        page = await MeetingService(self.session).list_timeline(
            principal, direction="past", q=q, limit=PER_KIND + 1
        )
        return [
            SearchHit(
                kind="meeting",
                id=str(m.id),
                title=m.title,
                subtitle=m.gremium_name,
                url=HIT_URL["meeting"].format(id=m.id),
            )
            for m in page.items
        ]

    async def _invoices(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Requires one of the budget read permissions, like `GET /api/invoices`."""
        if not _has_budget_read(principal):
            return []
        from app.modules.budget.tree.service import BudgetTreeService

        page = await BudgetTreeService(self.session).list_invoices_paged(
            q=q, limit=PER_KIND + 1, offset=0
        )
        return [
            SearchHit(
                kind="invoice",
                id=str(inv.id),
                title=inv.number or inv.supplier or str(inv.id),
                subtitle=_money(inv.gross_amount, inv.supplier),
                url=HIT_URL["invoice"].format(id=inv.id),
            )
            for inv in page.items
        ]

    async def _expenses(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Requires one of the budget read permissions, like `GET /api/expenses`."""
        if not _has_budget_read(principal):
            return []
        from app.modules.budget.tree.service import BudgetTreeService

        page = await BudgetTreeService(self.session).list_expenses_paged(
            q=q, limit=PER_KIND + 1, offset=0
        )
        return [
            SearchHit(
                kind="expense",
                id=str(e.id),
                title=e.description or str(e.id),
                subtitle=_money(e.amount, e.correspondent),
                url=HIT_URL["expense"].format(id=e.id),
            )
            for e in page.items
        ]

    async def _budgets(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Cost centres. Scoped the way `GET /api/budgets` scopes its tree.

        A holder of a global budget permission sees every node. Anyone else sees the
        nodes of the Gremien they belong to, through `view_gremium_id`, which is the
        column the tree endpoint filters roots on.
        """
        from app.modules.admin.gremium_roles import gremium_member_ids

        where, rank = trigram_rank(
            q, [Budget.name, Budget.path_key], dialect=dialect_of(self.session)
        )
        stmt = select(Budget).where(where, Budget.hidden_in_budget.is_(False))
        if not _has_budget_read(principal):
            member = await gremium_member_ids(self.session, principal.sub)
            if not member:
                return []
            stmt = stmt.where(Budget.view_gremium_id.in_(member))
        rows = (await self.session.scalars(stmt.order_by(rank.desc()).limit(PER_KIND + 1))).all()
        return [
            SearchHit(
                kind="budget",
                id=str(b.id),
                title=b.name,
                subtitle=b.path_key,
                url=HIT_URL["budget"].format(id=b.id),
            )
            for b in rows
        ]

    async def _gremien(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Committees, for a caller who can act on one."""
        # Gate BEFORE the query. A Gremium row links to the members page, which only an
        # administrator may open; anyone else would get a label with nowhere to go, and
        # a gate after the query would pay for a scan nobody is allowed to see.
        if not (principal.has("admin.gremien") or principal.has("admin.users")):
            return []
        where, rank = trigram_rank(
            q, [Gremium.name, Gremium.slug], dialect=dialect_of(self.session)
        )
        rows = (
            await self.session.scalars(
                select(Gremium).where(where).order_by(rank.desc()).limit(PER_KIND + 1)
            )
        ).all()
        return [
            SearchHit(
                kind="gremium",
                id=str(g.id),
                title=g.name,
                subtitle=g.slug,
                url=HIT_URL["gremium"].format(id=g.id),
            )
            for g in rows
        ]

    async def _principals(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """People. Reuses `search_principals`, behind the same permission pair that
        gates `GET /api/admin/principals`.
        """
        if not (principal.has("admin.users") or principal.has("admin.gremien")):
            return []
        from app.modules.admin.service.service import ConfigService

        rows = await ConfigService(self.session).search_principals(q, limit=PER_KIND + 1)
        return [
            SearchHit(
                kind="principal",
                id=str(p.id),
                title=p.display_name or p.email or p.sub,
                subtitle=p.email if p.display_name else None,
                url=HIT_URL["principal"].format(id=quote(p.sub)),
            )
            for p in rows
        ]


def _has_budget_read(principal: Principal) -> bool:
    """The permission trio that `GET /api/invoices` and `/api/expenses` accept."""
    return any(principal.has(p) for p in ("budget.view", "budget.structure", "budget.book"))


def _money(amount: Decimal | None, other: str | None) -> str | None:
    """Join an amount and a name into one subtitle line, skipping what is missing."""
    parts = [p for p in (f"{amount}" if amount is not None else None, other) if p]
    return " · ".join(parts) or None


__all__ = ["PER_KIND", "SearchService"]
