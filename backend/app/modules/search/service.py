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
from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import quote

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.access import READ_ALL_PERMISSION, READ_PERMISSION
from app.modules.budget.access import has_budget_read
from app.modules.budget.tree_models import Budget
from app.modules.gremien.models import Gremium
from app.modules.search.schemas import SearchHit, SearchKind, SearchResults
from app.modules.site_config.features import Feature, active_features
from app.shared.i18n import pick_lang, resolve_i18n
from app.shared.search import dialect_of, trigram_rank

if TYPE_CHECKING:
    from app.modules.auth.principal import Principal

log = logging.getLogger(__name__)

#: One search source: the query, the caller and the language give its hits.
type Source = Callable[[str, Principal, str], Awaitable[list[SearchHit]]]

#: Hits per kind. Small on purpose: a palette is a way to jump to one thing, not a
#: report. The client says so when a source hits the cap.
PER_KIND = 5

#: Below this the query matches too much to be useful and every source scans.
MIN_QUERY_LENGTH = 2

#: The title of a record that has no name of its own. A raw id in the palette tells the
#: reader nothing, so a nameless record reads as "untitled" in the reader's language.
UNTITLED: Mapping[str, str] = {"de": "Ohne Titel", "en": "Untitled"}

#: The subtitle of a Gremium hit: the kind only, in the reader's language. The
#: slug is an internal key and tells the reader nothing.
GREMIUM_SUBTITLE: Mapping[str, str] = {"de": "Gremium", "en": "Committee"}

#: The title of an account without a name and an e-mail. The `sub` is an internal
#: key: the user page shows it only in the tooltip.
UNNAMED: Mapping[str, str] = {"de": "Ohne Namen", "en": "No name"}

#: Where a hit of each kind sends the reader.
#:
#: Every template names the record: a path segment where the record has a page of its
#: own, and a filter the list applies where it does not. A bare list URL would drop the
#: reader back into the search they just ran.
#:
#: One table rather than an f-string in each source, so a new kind cannot ship a URL
#: that forgets which record it is about. A principal hit links by ``sub``, not by the
#: row id, because the principal search matches on it. A to-do hit names the card only,
#: and the page opens the board that the card is on now.
HIT_URL: Mapping[SearchKind, str] = {
    "application": "/applications/{id}",
    "meeting": "/meetings/{id}",
    "invoice": "/invoices?id={id}",
    "expense": "/expenses?id={id}",
    "budget": "/budget?costCentre={id}",
    "gremium": "/admin/committees/{id}/members",
    "principal": "/admin/users?q={id}",
    "ticket": "/tickets/{id}",
    "todo": "/todos?card={id}",
    "event": "/todos?card={id}",
}

#: The features a source needs. A source without an entry belongs to no feature.
SOURCE_FEATURE: Mapping[str, frozenset[Feature]] = {
    "meeting": frozenset({Feature.MEETINGS}),
    "invoice": frozenset({Feature.INVOICES}),
    "expense": frozenset({Feature.BUDGET}),
    "budget": frozenset({Feature.BUDGET}),
    "ticket": frozenset({Feature.TICKETS}),
    "todo": frozenset({Feature.TODOS}),
    "event": frozenset({Feature.TODOS}),
}

#: The status of a ticket hit, in the reader's language.
TICKET_STATUS: Mapping[str, Mapping[str, str]] = {
    "new": {"de": "Neu", "en": "New"},
    "in_progress": {"de": "In Arbeit", "en": "In progress"},
    "done": {"de": "Erledigt", "en": "Done"},
    "rejected": {"de": "Abgelehnt", "en": "Rejected"},
}


class SearchService:
    """Global search over every source, each behind the gate of its own module.

    Each source asks its own module, and its docstring names the gate it reuses, so a
    reader can check the claim without following the call.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a session."""
        self.session = session

    async def search(self, q: str, principal: Principal, *, lang: str = "de") -> SearchResults:
        """Search every source the principal may read.

        Returns an empty result for a query that is too short rather than an error: the
        palette calls this on every keystroke, and the first keystroke is not a mistake.

        A hit is one flat line, so an i18n label has to be resolved here rather than left
        for the client the way a list item leaves it. `lang` decides which translation.

        The sources run in sequence, not gathered, because they share one AsyncSession
        and a session is not safe for concurrent use; each query is small and indexed. A
        broken source is logged and listed in ``failed``, so it does not empty the
        palette. A source of a feature that is off is not asked, so the search returns
        no hit of it.
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
            "ticket": self._tickets,
            "todo": self._todos,
            "event": self._events,
        }
        enabled = await active_features(self.session)
        outcomes = [
            (name, await _answer(name, run, query, principal, lang))
            for name, run in sources.items()
            if SOURCE_FEATURE.get(name, enabled) <= enabled
        ]
        answered = [found for _, found in outcomes if found is not None]
        return SearchResults(
            hits=[hit for found in answered for hit in found[:PER_KIND]],
            truncated=any(len(found) > PER_KIND for found in answered),
            failed=[name for name, found in outcomes if found is None],
        )

    async def _applications(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Reuses `ApplicationsService.list_applications`, gated exactly as its router.

        A principal without a global read sees only their own applications plus the
        committee read scope, which the service resolves from the Gremium memberships.
        Such a principal gets no search over the isPII values of other applications.
        Archived rows are included, because someone who searches by name looks for one
        record, and archiving it does not make it stop existing.
        """
        from app.modules.applications.service import ApplicationsService

        can_read = principal.has(READ_PERMISSION) or principal.has(READ_ALL_PERMISSION)
        page = await ApplicationsService(self.session).list_applications(
            q=q,
            owner_sub=None if can_read else principal.sub,
            committee_sub=None if can_read else principal.sub,
            hide_pii_in_search=not can_read,
            archived=None,
            limit=PER_KIND + 1,
            offset=0,
        )
        return [
            SearchHit(
                kind="application",
                id=str(item.id),
                title=item.title or _untitled(lang),
                subtitle=(
                    resolve_i18n(item.state.label, lang, "de") if item.state is not None else None
                ),
                url=HIT_URL["application"].format(id=item.id),
                archived=item.archived_at is not None,
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
        if not has_budget_read(principal):
            return []
        from app.modules.budget.tree.service import BudgetTreeService

        page = await BudgetTreeService(self.session).list_invoices_paged(
            q=q, limit=PER_KIND + 1, offset=0
        )
        return [
            SearchHit(
                kind="invoice",
                id=str(inv.id),
                title=inv.number or inv.supplier or _untitled(lang),
                subtitle=_money(inv.gross_amount, inv.supplier),
                url=HIT_URL["invoice"].format(id=inv.id),
            )
            for inv in page.items
        ]

    async def _expenses(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Requires one of the budget read permissions, like `GET /api/expenses`."""
        if not has_budget_read(principal):
            return []
        from app.modules.budget.tree.service import BudgetTreeService

        page = await BudgetTreeService(self.session).list_expenses_paged(
            q=q, limit=PER_KIND + 1, offset=0
        )
        return [
            SearchHit(
                kind="expense",
                id=str(e.id),
                title=e.description or _untitled(lang),
                subtitle=_money(e.amount, e.correspondent),
                url=HIT_URL["expense"].format(id=e.id),
            )
            for e in page.items
        ]

    async def _budgets(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Cost centres. Scoped the way `GET /api/budgets` scopes its tree.

        A holder of a global budget permission sees every node. Anyone else sees the
        nodes of the Gremien they belong to as member or pool substitute
        (`gremium_reader_ids`), through `view_gremium_id`, which is the
        column the tree endpoint filters roots on.
        """
        where, rank = trigram_rank(
            q, [Budget.name, Budget.path_key], dialect=dialect_of(self.session)
        )
        scope = await self._budget_scope(principal)
        if scope is None:
            return []
        stmt = select(Budget).where(where, Budget.hidden_in_budget.is_(False), *scope)
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

    async def _budget_scope(self, principal: Principal) -> tuple[ColumnElement[bool], ...] | None:
        """Return the extra filter of the cost-centre search, or `None` for no visible node.

        A global budget permission needs no filter. Anyone else is limited to the nodes of
        the Gremien they read, and a caller who reads no Gremium sees no node at all.
        """
        from app.modules.gremien.gremium_roles import gremium_reader_ids

        if has_budget_read(principal):
            return ()
        member = await gremium_reader_ids(self.session, principal.sub)
        return (Budget.view_gremium_id.in_(member),) if member else None

    async def _gremien(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Search the committees, for a caller who can act on one.

        The gate comes BEFORE the query. A Gremium hit links to the members page, which
        only an administrator may open, so anyone else would get a label with nowhere to
        go, and a gate after the query would pay for a scan nobody may see.
        """
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
                subtitle=pick_lang(GREMIUM_SUBTITLE, lang),
                url=HIT_URL["gremium"].format(id=g.id),
            )
            for g in rows
        ]

    async def _principals(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Search people with `search_principals`.

        The gate is the permission pair of `GET /api/admin/principals`.
        """
        if not (principal.has("admin.users") or principal.has("admin.gremien")):
            return []
        from app.modules.admin.service.service import ConfigService

        rows = await ConfigService(self.session).search_principals(q, limit=PER_KIND + 1)
        return [
            SearchHit(
                kind="principal",
                id=str(p.id),
                title=p.display_name or p.email or pick_lang(UNNAMED, lang),
                subtitle=p.email if p.display_name else None,
                url=HIT_URL["principal"].format(id=quote(p.sub)),
            )
            for p in rows
        ]

    async def _tickets(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Reuses `TicketService.list`, behind `ticket.manage` like `GET /api/tickets`."""
        from app.modules.tickets.access import TICKET_MANAGE
        from app.modules.tickets.service import TicketService

        if not principal.has(TICKET_MANAGE):
            return []
        page = await TicketService(self.session).list(q=q, limit=PER_KIND + 1)
        return [
            SearchHit(
                kind="ticket",
                id=str(t.id),
                title=f"{t.number} · {t.title}",
                subtitle=pick_lang(TICKET_STATUS[t.status], lang),
                url=HIT_URL["ticket"].format(id=t.id),
            )
            for t in page.items
        ]

    async def _todos(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Reuses `TodoService.search`, behind the board read rule of the todos module."""
        from app.modules.todos.links import card_url
        from app.modules.todos.service import TodoService

        rows = await TodoService(self.session).search(q, principal, limit=PER_KIND + 1)
        return [
            SearchHit(
                kind="todo",
                id=str(card.id),
                title=card.title,
                subtitle=f"{board.name} · {column.name}",
                url=card_url(card.id),
            )
            for card, board, column in rows
        ]

    async def _events(self, q: str, principal: Principal, lang: str) -> list[SearchHit]:
        """Reuses `TodoService.search_events`, behind the board read rule of the todos module.

        Archived Events are hits too, because the next edition is planned from them
        (spec 000485).
        """
        from app.modules.todos.links import card_url
        from app.modules.todos.service import TodoService

        rows = await TodoService(self.session).search_events(q, principal, limit=PER_KIND + 1)
        return [
            SearchHit(
                kind="event",
                id=str(card.id),
                title=card.title,
                subtitle=" · ".join(
                    p for p in (_days(row.starts_on, row.ends_on), board.name) if p
                ),
                url=card_url(card.id),
                archived=card.archived_at is not None,
            )
            for card, board, row in rows
        ]


def _days(start: date | None, end: date | None) -> str | None:
    """The dates of an Event as ``DD.MM.YYYY`` or ``DD.MM.YYYY–DD.MM.YYYY``."""
    match start:
        case None:
            return None
        case date():
            first = start.strftime("%d.%m.%Y")
            return first if end is None or end == start else f"{first}–{end.strftime('%d.%m.%Y')}"


async def _answer(
    name: str, run: Source, query: str, principal: Principal, lang: str
) -> list[SearchHit] | None:
    """Ask one source, or log its failure and return `None`.

    A broken source must not empty the palette, so the failure ends here and the caller
    lists the source in ``failed``.
    """
    try:
        return await run(query, principal, lang)
    except Exception:
        log.exception("search source %s failed", name)
        return None


def _untitled(lang: str) -> str:
    """The title of a nameless record, in the reader's language (German as fallback)."""
    return pick_lang(UNTITLED, lang)


def _money(amount: Decimal | None, other: str | None) -> str | None:
    """Join an amount and a name into one subtitle line, skipping what is missing."""
    parts = [p for p in (f"{amount}" if amount is not None else None, other) if p]
    return " · ".join(parts) or None


__all__ = ["PER_KIND", "UNTITLED", "SearchService"]
