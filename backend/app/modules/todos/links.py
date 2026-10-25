"""Link targets of a card: resolve them per viewer, and search them for the picker.

A card links to an application, a meeting, an agenda item, a vote, a gremium, an
invoice, a booking, a ticket or another card. Each kind has the read rule of its own
module:

* application — the application read access (``resolve_app_read``), confirmed only;
* meeting — the meeting read scope (``meeting_read_scope``);
* agenda_item — the read scope of its meeting;
* vote — the read scope of the vote list (``voting.listing.read_scope``, the SQL form
  of ``VotingService.assert_can_read``);
* gremium — the gate of the tab "Gremien" (``gremium_view_scope``, the set form of
  ``can_view_gremium``: ``gremium.view_all`` or an active membership);
* invoice, expense — the gate of ``GET /api/invoices`` and ``GET /api/expenses``
  (``budget.access.has_budget_read``);
* ticket — ``ticket.manage``;
* todo — the board read rule (``BoardAccess``).

A target that the viewer cannot read resolves as not accessible: no title, no url,
no detail. The frontend shows "<Kind> (kein Zugriff)". The resolver loads each kind
in one query and caches the rights per request, because a board read resolves one
link per card.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.access import (
    READ_ALL_PERMISSION,
    READ_PERMISSION,
    resolve_app_read,
)
from app.modules.applications.models import Application
from app.modules.applications.service.service_base import _title_of
from app.modules.auth.policy import gremium_view_scope
from app.modules.auth.principal import Principal
from app.modules.budget.access import has_budget_read
from app.modules.budget.tree_models import Budget, BudgetExpense, Invoice
from app.modules.flow.models import State
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.tickets.models import Ticket
from app.modules.tickets.service import format_number
from app.modules.todos.access import BoardAccess
from app.modules.todos.models import LINK_KINDS, TodoBoard, TodoCard, TodoColumn
from app.modules.todos.schemas import TodoLinkDetail, TodoLinkTarget
from app.modules.voting.listing import read_scope as vote_read_scope
from app.modules.voting.models import Vote
from app.shared.errors import ForbiddenError
from app.shared.search import dialect_of, escape_like, trigram_rank

#: The most hits of one kind in the link picker.
PER_KIND = 5
#: Every status of a vote: the picker also offers a draft, which a card often prepares.
VOTE_STATUSES = ("open", "draft", "closed", "cancelled")

LinkRef = tuple[str, uuid.UUID]


@dataclass(frozen=True, slots=True)
class Resolved:
    """One link target as the viewer sees it."""

    accessible: bool
    title: str | None = None
    url: str | None = None
    detail: TodoLinkDetail | None = None


HIDDEN = Resolved(accessible=False)


def _iso(value: object) -> str | None:
    return value.isoformat() if value is not None else None  # type: ignore[attr-defined]


def _money(value: object) -> str | None:
    return str(value) if value is not None else None


def card_url(card_id: uuid.UUID) -> str:
    """The app route of a card: the card id only.

    The page reads the card and opens its board with the drawer, so the link stays valid
    when the card moves to another board.
    """
    return f"/todos?card={card_id}"


class LinkResolver:
    """Resolve and search link targets for one principal."""

    def __init__(self, session: AsyncSession, access: BoardAccess) -> None:
        """Bind the resolver to a session and the board access check."""
        self.session = session
        self.access = access
        self._meeting_scope: tuple[set[uuid.UUID] | None, set[uuid.UUID]] | None = None
        self._gremium_scope: tuple[set[uuid.UUID] | None] | None = None

    async def _meetings_scope(
        self, principal: Principal
    ) -> tuple[set[uuid.UUID] | None, set[uuid.UUID]]:
        """The read scope of ``assert_can_read``: visible gremien (None = all), delegations."""
        if self._meeting_scope is None:
            from app.modules.livevote.service import MeetingService

            self._meeting_scope = await MeetingService(self.session).meeting_read_scope(principal)
        return self._meeting_scope

    async def _meeting_visible(self, meeting: Meeting, principal: Principal) -> bool:
        gremien, delegated = await self._meetings_scope(principal)
        return gremien is None or meeting.gremium_id in gremien or meeting.id in delegated

    async def _gremien_scope(self, principal: Principal) -> set[uuid.UUID] | None:
        """The gremien of the tab "Gremien" for the principal (None = all), cached."""
        if self._gremium_scope is None:
            self._gremium_scope = (await gremium_view_scope(self.session, principal),)
        return self._gremium_scope[0]

    async def _application_readable(self, app: Application, principal: Principal) -> bool:
        if app.email_confirmed_at is None:
            return False
        if principal.has(READ_PERMISSION) or principal.has(READ_ALL_PERMISSION):
            return True
        try:
            await resolve_app_read(self.session, app.id, principal, None)
        except ForbiddenError:
            return False
        return True

    async def resolve(
        self, refs: Iterable[LinkRef], principal: Principal
    ) -> dict[LinkRef, Resolved]:
        """Resolve every ``(kind, target id)`` pair; a missing target is not accessible."""
        by_kind: dict[str, set[uuid.UUID]] = {}
        for kind, target_id in refs:
            by_kind.setdefault(kind, set()).add(target_id)
        out: dict[LinkRef, Resolved] = {}
        handlers = {
            "application": self._applications,
            "meeting": self._meetings,
            "agenda_item": self._agenda_items,
            "vote": self._votes,
            "gremium": self._gremien,
            "invoice": self._invoices,
            "expense": self._expenses,
            "ticket": self._tickets,
            "todo": self._todos,
        }
        for kind in LINK_KINDS:
            ids = by_kind.get(kind)
            if not ids:
                continue
            found = await handlers[kind](ids, principal)
            for target_id in ids:
                out[(kind, target_id)] = found.get(target_id, HIDDEN)
        return out

    async def readable(self, kind: str, target_id: uuid.UUID, principal: Principal) -> bool:
        """Tell if the principal reads the target (the rule of ``POST .../links``)."""
        return (await self.resolve([(kind, target_id)], principal))[(kind, target_id)].accessible

    async def _state_labels(self, apps: Iterable[Application]) -> dict[uuid.UUID, dict[str, str]]:
        ids = {a.current_state_id for a in apps if a.current_state_id is not None}
        if not ids:
            return {}
        rows = (
            await self.session.execute(select(State.id, State.label_i18n).where(State.id.in_(ids)))
        ).all()
        return {sid: dict(label or {}) for sid, label in rows}

    async def _applications(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, Resolved]:
        apps = list(
            (await self.session.scalars(select(Application).where(Application.id.in_(ids)))).all()
        )
        readable = [a for a in apps if await self._application_readable(a, principal)]
        labels = await self._state_labels(readable)
        return {
            a.id: Resolved(
                accessible=True,
                title=_title_of(a.data) or "",
                url=f"/applications/{a.id}",
                detail=TodoLinkDetail(
                    state_label=(
                        labels.get(a.current_state_id) if a.current_state_id is not None else None
                    )
                ),
            )
            for a in readable
        }

    async def _meetings(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, Resolved]:
        meetings = list(
            (await self.session.scalars(select(Meeting).where(Meeting.id.in_(ids)))).all()
        )
        out: dict[uuid.UUID, Resolved] = {}
        for m in meetings:
            if await self._meeting_visible(m, principal):
                out[m.id] = Resolved(
                    accessible=True,
                    title=m.title,
                    url=f"/meetings/{m.id}",
                    detail=TodoLinkDetail(date=_iso(m.date)),
                )
        return out

    async def _agenda_items(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, Resolved]:
        rows = (
            await self.session.execute(
                select(MeetingAgendaItem, Meeting)
                .join(Meeting, Meeting.id == MeetingAgendaItem.meeting_id)
                .where(MeetingAgendaItem.id.in_(ids))
            )
        ).all()
        visible = [(item, m) for item, m in rows if await self._meeting_visible(m, principal)]
        if not visible:
            return {}
        numbers = await self._agenda_numbers({m.id for _, m in visible})
        titles = await self._application_titles(
            {i.application_id for i, _ in visible if i.application_id is not None}
        )
        out: dict[uuid.UUID, Resolved] = {}
        for item, m in visible:
            title = (
                titles.get(item.application_id) if item.application_id is not None else None
            ) or (item.title or "")
            out[item.id] = Resolved(
                accessible=True,
                title=title,
                url=f"/meetings/{m.id}?item={item.id}",
                detail=TodoLinkDetail(
                    date=_iso(m.date), meeting_title=m.title, position=numbers.get(item.id)
                ),
            )
        return out

    async def _agenda_numbers(self, meeting_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Return the 1-based TOP number of every item of the meetings (agenda order)."""
        number = (
            func.row_number()
            .over(
                partition_by=MeetingAgendaItem.meeting_id,
                order_by=(
                    MeetingAgendaItem.position.asc(),
                    MeetingAgendaItem.created_at.asc(),
                    MeetingAgendaItem.id.asc(),
                ),
            )
            .label("number")
        )
        rows = (
            await self.session.execute(
                select(MeetingAgendaItem.id, number).where(
                    MeetingAgendaItem.meeting_id.in_(meeting_ids)
                )
            )
        ).all()
        return {item_id: int(n) for item_id, n in rows}

    async def _application_titles(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(Application.id, Application.data).where(Application.id.in_(ids))
            )
        ).all()
        return {aid: _title_of(data) or "" for aid, data in rows}

    async def _readable_application_titles(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, str]:
        """The titles of the applications in ``ids`` that the principal can read."""
        if not ids:
            return {}
        stmt = select(Application).where(Application.id.in_(ids))
        apps = (await self.session.scalars(stmt)).all()
        return {
            a.id: _title_of(a.data) or ""
            for a in apps
            if await self._application_readable(a, principal)
        }

    async def _votes(self, ids: set[uuid.UUID], principal: Principal) -> dict[uuid.UUID, Resolved]:
        rows = (
            await self.session.execute(
                select(Vote, Meeting.title, Meeting.date)
                .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
                .where(Vote.id.in_(ids), await vote_read_scope(self.session, principal))
            )
        ).all()
        if not rows:
            return {}
        titles = await self._readable_application_titles(
            {v.application_id for v, _t, _d in rows if not v.question and v.application_id},
            principal,
        )
        out: dict[uuid.UUID, Resolved] = {}
        for vote, meeting_title, meeting_date in rows:
            title = vote.question or (
                titles.get(vote.application_id) if vote.application_id is not None else None
            )
            out[vote.id] = Resolved(
                accessible=True,
                title=title or "",
                url=f"/voting/{vote.id}",
                detail=TodoLinkDetail(
                    meeting_title=meeting_title,
                    date=_iso(meeting_date),
                    vote_status=vote.status,  # type: ignore[arg-type]
                    vote_result=vote.result,  # type: ignore[arg-type]
                ),
            )
        return out

    async def _gremien(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, Resolved]:
        visible = await self._gremien_scope(principal)
        wanted = ids if visible is None else ids & visible
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(Gremium.id, Gremium.name).where(Gremium.id.in_(wanted))
            )
        ).all()
        return {
            gid: Resolved(
                accessible=True, title=name, url=f"/gremien/{gid}", detail=TodoLinkDetail()
            )
            for gid, name in rows
        }

    async def _invoices(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, Resolved]:
        if not has_budget_read(principal):
            return {}
        invoices = list(
            (await self.session.scalars(select(Invoice).where(Invoice.id.in_(ids)))).all()
        )
        return {
            inv.id: Resolved(
                accessible=True,
                title=inv.number or inv.supplier or "",
                url=f"/invoices?id={inv.id}",
                detail=TodoLinkDetail(
                    number=inv.number,
                    counterparty=inv.supplier,
                    amount=_money(inv.gross_amount),
                    date=_iso(inv.issue_date),
                    invoice_status=inv.status,  # type: ignore[arg-type]
                ),
            )
            for inv in invoices
        }

    async def _expenses(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, Resolved]:
        """Resolve expense links; a sub-booking links to its parent.

        The list shows a sub-booking under its parent only, so the deep link selects the
        parent.
        """
        if not has_budget_read(principal):
            return {}
        rows = (
            await self.session.execute(
                select(BudgetExpense, Budget.path_key)
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .where(BudgetExpense.id.in_(ids))
            )
        ).all()
        out: dict[uuid.UUID, Resolved] = {}
        for exp, path_key in rows:
            row_id = exp.parent_expense_id or exp.id
            out[exp.id] = Resolved(
                accessible=True,
                title=exp.description,
                url=f"/expenses?id={row_id}",
                detail=TodoLinkDetail(
                    amount=_money(exp.amount),
                    booking_kind=exp.kind,  # type: ignore[arg-type]
                    cost_centre=path_key,
                    counterparty=exp.correspondent,
                    date=_iso(exp.payment_date or exp.invoice_date),
                ),
            )
        return out

    async def _tickets(
        self, ids: set[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, Resolved]:
        if not principal.has(TICKET_MANAGE):
            return {}
        tickets = list((await self.session.scalars(select(Ticket).where(Ticket.id.in_(ids)))).all())
        return {
            t.id: Resolved(
                accessible=True,
                title=t.title,
                url=f"/tickets/{t.id}",
                detail=TodoLinkDetail(number=format_number(t.number), status=t.status),  # type: ignore[arg-type]
            )
            for t in tickets
        }

    async def _todos(self, ids: set[uuid.UUID], principal: Principal) -> dict[uuid.UUID, Resolved]:
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard, TodoColumn)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .where(TodoCard.id.in_(ids))
            )
        ).all()
        out: dict[uuid.UUID, Resolved] = {}
        for card, board, column in rows:
            if await self.access.can_read(board, principal):
                out[card.id] = Resolved(
                    accessible=True,
                    title=card.title,
                    url=card_url(card.id),
                    detail=TodoLinkDetail(
                        board_name=board.name, column_name=column.name, is_done=column.is_done
                    ),
                )
        return out

    async def search(
        self,
        q: str,
        kind: str,
        principal: Principal,
        *,
        exclude_card_id: uuid.UUID | None = None,
    ) -> list[TodoLinkTarget]:
        """Search the link targets that the principal may read, ``PER_KIND`` per kind."""
        term = q.strip()
        kinds: Sequence[str] = LINK_KINDS if kind == "all" else (kind,)
        found: list[TodoLinkTarget] = []
        for current in kinds:
            ids = await self._candidates(current, term, principal, exclude_card_id)
            resolved = await self.resolve([(current, i) for i in ids], principal)
            found.extend(
                TodoLinkTarget(
                    kind=current,  # type: ignore[arg-type]
                    target_id=i,
                    title=r.title or "",
                    detail=r.detail or TodoLinkDetail(),
                )
                for i in ids
                if (r := resolved[(current, i)]).accessible
            )
        return found

    async def _candidates(
        self,
        kind: str,
        term: str,
        principal: Principal,
        exclude_card_id: uuid.UUID | None,
    ) -> list[uuid.UUID]:
        pattern = f"%{escape_like(term)}%"
        if kind == "application":
            return await self._application_candidates(term, principal)
        if kind == "meeting":
            return await self._meeting_candidates(pattern, principal)
        if kind == "agenda_item":
            return await self._agenda_candidates(pattern, principal)
        if kind == "vote":
            return await self._vote_candidates(term, principal)
        if kind == "gremium":
            return await self._gremium_candidates(term, principal)
        if kind == "invoice":
            return await self._invoice_candidates(term, principal)
        if kind == "expense":
            return await self._expense_candidates(term, principal)
        if kind == "ticket":
            return await self._ticket_candidates(term, principal)
        return await self._todo_candidates(pattern, principal, exclude_card_id)

    async def _application_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """Reuses ``ApplicationsService.list_applications`` with the gate of its router."""
        from app.modules.applications.service import ApplicationsService

        can_read = principal.has(READ_PERMISSION) or principal.has(READ_ALL_PERMISSION)
        page = await ApplicationsService(self.session).list_applications(
            q=term,
            owner_sub=None if can_read else principal.sub,
            committee_sub=None if can_read else principal.sub,
            hide_pii_in_search=not can_read,
            archived=None,
            limit=PER_KIND,
            offset=0,
        )
        return [item.id for item in page.items]

    async def _meeting_scope_condition(self, principal: Principal) -> ColumnElement[bool] | None:
        gremien, delegated = await self._meetings_scope(principal)
        if gremien is None:
            return None
        return or_(Meeting.gremium_id.in_(gremien), Meeting.id.in_(delegated))

    async def _meeting_candidates(self, pattern: str, principal: Principal) -> list[uuid.UUID]:
        stmt = select(Meeting.id).where(Meeting.title.ilike(pattern, escape="\\"))
        scope = await self._meeting_scope_condition(principal)
        if scope is not None:
            stmt = stmt.where(scope)
        stmt = stmt.order_by(Meeting.date.desc().nulls_last(), Meeting.id).limit(PER_KIND)
        return list((await self.session.scalars(stmt)).all())

    async def _agenda_candidates(self, pattern: str, principal: Principal) -> list[uuid.UUID]:
        app_title = cast(Application.data["title"].astext, String)
        stmt = (
            select(MeetingAgendaItem.id)
            .join(Meeting, Meeting.id == MeetingAgendaItem.meeting_id)
            .outerjoin(Application, Application.id == MeetingAgendaItem.application_id)
            .where(
                or_(
                    MeetingAgendaItem.title.ilike(pattern, escape="\\"),
                    app_title.ilike(pattern, escape="\\"),
                    Meeting.title.ilike(pattern, escape="\\"),
                )
            )
        )
        scope = await self._meeting_scope_condition(principal)
        if scope is not None:
            stmt = stmt.where(scope)
        stmt = stmt.order_by(
            Meeting.date.desc().nulls_last(),
            MeetingAgendaItem.position,
            MeetingAgendaItem.id,
        ).limit(PER_KIND)
        return list((await self.session.scalars(stmt)).all())

    async def _vote_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """Reuses ``voting.listing.list_votes`` (``GET /votes``), with every status."""
        from app.modules.voting.listing import list_votes

        page = await list_votes(
            self.session, principal, statuses=VOTE_STATUSES, q=term, limit=PER_KIND, offset=0
        )
        return [v.id for v in page.items]

    async def _gremium_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """The trigram match of the search source on name and slug, in the Gremien scope."""
        visible = await self._gremien_scope(principal)
        if visible is not None and not visible:
            return []
        where, rank = trigram_rank(
            term, [Gremium.name, Gremium.slug], dialect=dialect_of(self.session)
        )
        stmt = select(Gremium.id).where(where)
        if visible is not None:
            stmt = stmt.where(Gremium.id.in_(visible))
        stmt = stmt.order_by(rank.desc(), Gremium.name, Gremium.id).limit(PER_KIND)
        return list((await self.session.scalars(stmt)).all())

    async def _invoice_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """Reuses ``list_invoices_paged`` behind the gate of ``GET /invoices``."""
        if not has_budget_read(principal):
            return []
        from app.modules.budget.tree.service import BudgetTreeService

        page = await BudgetTreeService(self.session).list_invoices_paged(
            q=term, limit=PER_KIND, offset=0
        )
        return [inv.id for inv in page.items]

    async def _expense_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """Reuses ``list_expenses_paged`` behind the gate of ``GET /expenses``."""
        if not has_budget_read(principal):
            return []
        from app.modules.budget.tree.service import BudgetTreeService

        page = await BudgetTreeService(self.session).list_expenses_paged(
            q=term, limit=PER_KIND, offset=0
        )
        return [e.id for e in page.items]

    async def _ticket_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """Reuses ``TicketService.list``, behind ``ticket.manage`` like ``GET /tickets``."""
        if not principal.has(TICKET_MANAGE):
            return []
        from app.modules.tickets.service import TicketService

        page = await TicketService(self.session).list(q=term, limit=PER_KIND)
        return [t.id for t in page.items]

    async def _todo_candidates(
        self, pattern: str, principal: Principal, exclude_card_id: uuid.UUID | None
    ) -> list[uuid.UUID]:
        scope = await self.access.scope(principal)
        stmt = (
            select(TodoCard.id)
            .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
            .where(
                scope.condition(),
                TodoCard.archived_at.is_(None),
                TodoCard.title.ilike(pattern, escape="\\"),
            )
        )
        if exclude_card_id is not None:
            stmt = stmt.where(TodoCard.id != exclude_card_id)
        stmt = stmt.order_by(TodoCard.updated_at.desc(), TodoCard.id).limit(PER_KIND)
        return list((await self.session.scalars(stmt)).all())
