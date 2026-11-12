"""Link targets of a card: resolve them per viewer, and search them for the picker.

A card links to an application, a meeting, an agenda item, a vote, a Termin, a gremium,
an invoice, a booking, a cost centre, a ticket or another card. Each kind has the read rule
of its own module:

* application — the application read access (``resolve_app_read``), confirmed only;
* meeting — the meeting read scope (``meeting_read_scope``);
* agenda_item — the read scope of its meeting;
* vote — the read scope of the vote list (``voting.listing.read_scope``, the SQL form
  of ``VotingService.assert_can_read``);
* appointment (a Termin) — the read rule of the Termine (``calendar.appointments.readable``:
  the creator, an invited person, every person for a Termin that is for all or public);
* gremium — the gate of the tab "Gremien" (``gremium_view_scope``, the set form of
  ``can_view_gremium``: ``gremium.view_all`` or an active membership);
* invoice, expense — the gate of ``GET /api/invoices`` and ``GET /api/expenses``
  (``budget.access.has_budget_read``);
* budget (a cost centre) — every reader of the card sees its name and path key (spec
  000552); the url to the cost centre page and the link picker follow the gate of the
  budget pages (``has_budget_read``), so only a budget reader links one;
* ticket — ``ticket.manage``;
* todo — the board read rule (``BoardAccess``).

A card also gives read access to its links (spec 000487): a target that the viewer
cannot read by the rule of its kind resolves as ``granted`` when a card on a board
that the viewer reads links it. A granted target has no url, the card opens it in a
read-only sheet (``link_view``). The grant stops after one step: it comes only from
cards that the viewer reads by the board rule, never from a granted card. A ticket and
a gremium give no grant. A granted Termin gives its title, its start, its end and its
place only, never its description, its invitations or its answers. The link picker and
the link check of ``POST .../links`` use the rule of the kind only, so a person links
only what the person reads.

A target that the viewer cannot read resolves as not accessible: no title, no url,
no detail. The frontend shows "<Kind> (kein Zugriff)". The resolver loads each kind
in one query and caches the rights per request, because a board read resolves one
link per card.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.modules.calendar.appointments import AppointmentService
from app.modules.calendar.appointments import readable as appointment_readable
from app.modules.calendar.models import Appointment
from app.modules.flow.models import State
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.tickets.models import Ticket
from app.modules.tickets.service import format_number
from app.modules.todos.access import BoardAccess
from app.modules.todos.grouping import grouped
from app.modules.todos.models import (
    LINK_COLUMNS,
    LINK_KINDS,
    TodoBoard,
    TodoCard,
    TodoColumn,
    TodoLink,
)
from app.modules.todos.schemas import TodoLinkDetail, TodoLinkTarget
from app.modules.voting.listing import read_scope as vote_read_scope
from app.modules.voting.models import Vote
from app.shared.errors import ForbiddenError
from app.shared.search import dialect_of, escape_like, trigram_rank

#: The most hits of one kind in the link picker.
PER_KIND = 5
#: The newest cards that ``recent_cards`` offers before a search term (spec 000548).
RECENT_CARDS = 20
#: The shortest search term.
MIN_TERM = 2
#: Every status of a vote: the picker also offers a draft, which a card often prepares.
VOTE_STATUSES = ("open", "draft", "closed", "cancelled")

LinkRef = tuple[str, uuid.UUID]
#: The kinds that a card opens to its readers (spec 000487): every kind but the ticket,
#: which holds the report of a person outside the team, the gremium, and the cost centre,
#: which every reader of the card sees anyway.
GRANT_KINDS: frozenset[str] = frozenset(LINK_KINDS) - {"ticket", "gremium", "budget"}
#: No id passes the gate of its kind without the rule.
NONE: frozenset[uuid.UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class Resolved:
    """One link target as the viewer sees it."""

    accessible: bool
    title: str | None = None
    url: str | None = None
    detail: TodoLinkDetail | None = None
    granted: bool = False


HIDDEN = Resolved(accessible=False)


def _by_kind(refs: Iterable[LinkRef]) -> dict[str, frozenset[uuid.UUID]]:
    """Group the target ids by their kind, in the order of the first ref of each kind."""
    return {kind: frozenset(ids) for kind, ids in grouped(refs).items()}


def _iso(value: object) -> str | None:
    return value.isoformat() if value is not None else None  # type: ignore[attr-defined]


def _money(value: object) -> str | None:
    return str(value) if value is not None else None


def _present(condition: ColumnElement[bool] | None) -> tuple[ColumnElement[bool], ...]:
    """The condition as a ``WHERE`` part: nothing for ``None``."""
    return (condition,) if condition is not None else ()


def _agenda_item_target(
    item: MeetingAgendaItem,
    meeting: Meeting,
    titles: Mapping[uuid.UUID, str],
    numbers: Mapping[uuid.UUID, int],
) -> Resolved:
    """An agenda item, titled by its own title, else by its application."""
    title = (
        item.title
        or (titles.get(item.application_id) if item.application_id is not None else None)
        or ""
    )
    return Resolved(
        accessible=True,
        title=title,
        url=f"/meetings/{meeting.id}?item={item.id}",
        detail=TodoLinkDetail(
            date=_iso(meeting.date), meeting_title=meeting.title, position=numbers.get(item.id)
        ),
    )


def _vote_target(
    vote: Vote,
    meeting_title: str | None,
    meeting_date: object,
    titles: Mapping[uuid.UUID, str],
) -> Resolved:
    """A vote, titled by its question, else by its application."""
    title = vote.question or (
        titles.get(vote.application_id) if vote.application_id is not None else None
    )
    return Resolved(
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


def _expense_target(exp: BudgetExpense, path_key: str | None) -> Resolved:
    """A booking; a sub-booking links its parent row, because the list shows it there."""
    return Resolved(
        accessible=True,
        title=exp.description,
        url=f"/expenses?id={exp.parent_expense_id or exp.id}",
        detail=TodoLinkDetail(
            amount=_money(exp.amount),
            booking_kind=exp.kind,  # type: ignore[arg-type]
            cost_centre=path_key,
            counterparty=exp.correspondent,
            date=_iso(exp.payment_date or exp.invoice_date),
        ),
    )


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
        self, refs: Iterable[LinkRef], principal: Principal, *, grants: bool = True
    ) -> dict[LinkRef, Resolved]:
        """Resolve every ``(kind, target id)`` pair; a missing target is not accessible.

        With ``grants`` a target that the rule of its kind hides resolves as ``granted``
        when a card that the principal reads links it.
        """
        out = await self._resolve(_by_kind(refs), principal, None)
        if not grants:
            return out
        hidden = _by_kind(
            ref for ref, found in out.items() if not found.accessible and ref[0] in GRANT_KINDS
        )
        opened = {
            kind: ids
            for kind, ids in [(k, await self.granted(k, v, principal)) for k, v in hidden.items()]
            if ids
        }
        if not opened:
            return out
        more = await self._resolve(opened, principal, opened)
        return {
            **out,
            **{
                ref: Resolved(
                    accessible=True,
                    title=found.title,
                    detail=found.detail,
                    granted=True,
                )
                for ref, found in more.items()
                if found.accessible
            },
        }

    async def granted(
        self, kind: str, ids: AbstractSet[uuid.UUID], principal: Principal
    ) -> set[uuid.UUID]:
        """The ids of ``ids`` that a card on a board that the principal reads links."""
        if kind not in GRANT_KINDS or not ids:
            return set()
        column = getattr(TodoLink, LINK_COLUMNS[kind])
        scope = await self.access.scope(principal)
        rows = await self.session.scalars(
            select(column)
            .join(TodoCard, TodoCard.id == TodoLink.card_id)
            .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
            .where(column.in_(ids), scope.condition())
            .distinct()
        )
        return set(rows.all())

    async def _resolve(
        self,
        by_kind: Mapping[str, AbstractSet[uuid.UUID]],
        principal: Principal,
        opened: Mapping[str, AbstractSet[uuid.UUID]] | None,
    ) -> dict[LinkRef, Resolved]:
        """Run the handler of each kind; ``opened`` ids pass the gate of their kind."""
        handlers = {
            "application": self._applications,
            "meeting": self._meetings,
            "agenda_item": self._agenda_items,
            "vote": self._votes,
            "appointment": self._appointments,
            "gremium": self._gremien,
            "invoice": self._invoices,
            "expense": self._expenses,
            "budget": self._budgets,
            "ticket": self._tickets,
            "todo": self._todos,
        }
        found = {
            kind: await handlers[kind](
                by_kind[kind],
                principal,
                frozenset(opened.get(kind, ())) if opened is not None else NONE,
            )
            for kind in LINK_KINDS
            if by_kind.get(kind)
        }
        return {
            (kind, target_id): hits.get(target_id, HIDDEN)
            for kind, hits in found.items()
            for target_id in by_kind[kind]
        }

    async def readable(self, kind: str, target_id: uuid.UUID, principal: Principal) -> bool:
        """Tell if the principal reads the target (the rule of ``POST .../links``).

        A cost centre shows to every reader of the card, but only a budget reader links one.
        """
        if kind == "budget" and not has_budget_read(principal):
            return False
        resolved = await self.resolve([(kind, target_id)], principal, grants=False)
        return resolved[(kind, target_id)].accessible

    async def _state_labels(self, apps: Iterable[Application]) -> dict[uuid.UUID, dict[str, str]]:
        ids = {a.current_state_id for a in apps if a.current_state_id is not None}
        if not ids:
            return {}
        rows = (
            await self.session.execute(select(State.id, State.label_i18n).where(State.id.in_(ids)))
        ).all()
        return {sid: dict(label or {}) for sid, label in rows}

    async def _applications(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        apps = list(
            (await self.session.scalars(select(Application).where(Application.id.in_(ids)))).all()
        )
        readable = [
            a
            for a in apps
            if (a.id in open_ids and a.email_confirmed_at is not None)
            or await self._application_readable(a, principal)
        ]
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
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        meetings = list(
            (await self.session.scalars(select(Meeting).where(Meeting.id.in_(ids)))).all()
        )
        return {
            m.id: Resolved(
                accessible=True,
                title=m.title,
                url=f"/meetings/{m.id}",
                detail=TodoLinkDetail(date=_iso(m.date)),
            )
            for m in meetings
            if m.id in open_ids or await self._meeting_visible(m, principal)
        }

    async def _agenda_items(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        rows = (
            await self.session.execute(
                select(MeetingAgendaItem, Meeting)
                .join(Meeting, Meeting.id == MeetingAgendaItem.meeting_id)
                .where(MeetingAgendaItem.id.in_(ids))
            )
        ).all()
        visible = [
            (item, m)
            for item, m in rows
            if item.id in open_ids or await self._meeting_visible(m, principal)
        ]
        if not visible:
            return {}
        numbers = await self._agenda_numbers({m.id for _, m in visible})
        titles = await self._application_titles(
            {i.application_id for i, _ in visible if i.application_id is not None}
        )
        return {item.id: _agenda_item_target(item, m, titles, numbers) for item, m in visible}

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

    async def _votes(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        rows = (
            await self.session.execute(
                select(Vote, Meeting.title, Meeting.date)
                .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
                .where(
                    Vote.id.in_(ids),
                    or_(
                        await vote_read_scope(self.session, principal),
                        Vote.id.in_(open_ids),
                    ),
                )
            )
        ).all()
        if not rows:
            return {}
        untitled = {v.application_id for v, _t, _d in rows if not v.question and v.application_id}
        titles = (
            await self._application_titles(untitled)
            if open_ids
            else await self._readable_application_titles(untitled, principal)
        )
        return {
            vote.id: _vote_target(vote, meeting_title, meeting_date, titles)
            for vote, meeting_title, meeting_date in rows
        }

    async def _appointments(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        viewer = await AppointmentService(self.session).viewer(principal)
        rows = (
            await self.session.scalars(
                select(Appointment).where(
                    Appointment.id.in_(ids),
                    or_(appointment_readable(viewer), Appointment.id.in_(open_ids)),
                )
            )
        ).all()
        return {
            row.id: Resolved(
                accessible=True,
                title=row.title,
                url=f"/calendar?appointment={row.id}",
                detail=TodoLinkDetail(
                    date=_iso(row.starts_on),
                    end_date=_iso(row.ends_on),
                    start_time=_iso(row.start_time),
                    end_time=_iso(row.end_time),
                    place=row.place,
                ),
            )
            for row in rows
        }

    async def _gremien(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
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
                accessible=True, title=name, url=f"/committees/{gid}", detail=TodoLinkDetail()
            )
            for gid, name in rows
        }

    async def _invoices(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        wanted = ids if has_budget_read(principal) else ids & open_ids
        if not wanted:
            return {}
        invoices = list(
            (await self.session.scalars(select(Invoice).where(Invoice.id.in_(wanted)))).all()
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
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        """Resolve expense links; a sub-booking links to its parent.

        The list shows a sub-booking under its parent only, so the deep link selects the
        parent.
        """
        wanted = ids if has_budget_read(principal) else ids & open_ids
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(BudgetExpense, Budget.path_key)
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .where(BudgetExpense.id.in_(wanted))
            )
        ).all()
        return {exp.id: _expense_target(exp, path_key) for exp, path_key in rows}

    async def _budgets(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        """Resolve cost centre links: name and path key for each reader (spec 000552).

        The url follows the gate of the budget pages, so a reader without budget read sees
        the name without a way into the page.
        """
        rows = (
            await self.session.execute(
                select(Budget.id, Budget.name, Budget.path_key).where(Budget.id.in_(ids))
            )
        ).all()
        reads = has_budget_read(principal)
        return {
            bid: Resolved(
                accessible=True,
                title=name,
                url=f"/budget?costCentre={bid}" if reads else None,
                detail=TodoLinkDetail(cost_centre=path_key),
            )
            for bid, name, path_key in rows
        }

    async def _tickets(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
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

    async def _todos(
        self,
        ids: AbstractSet[uuid.UUID],
        principal: Principal,
        open_ids: frozenset[uuid.UUID] = NONE,
    ) -> dict[uuid.UUID, Resolved]:
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard, TodoColumn)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .where(TodoCard.id.in_(ids))
            )
        ).all()
        return {
            card.id: Resolved(
                accessible=True,
                title=card.title,
                url=card_url(card.id),
                detail=TodoLinkDetail(
                    board_name=board.name, column_name=column.name, is_done=column.is_done
                ),
            )
            for card, board, column in rows
            if card.id in open_ids or await self.access.can_read(board, principal)
        }

    async def search(
        self,
        q: str,
        kind: str,
        principal: Principal,
        *,
        exclude_card_id: uuid.UUID | None = None,
    ) -> list[TodoLinkTarget]:
        """Search the link targets that the principal may read, ``PER_KIND`` per kind.

        A term below ``MIN_TERM`` characters finds the newest cards for the kind ``todo``
        (``recent_cards``) and nothing for any other kind.
        """
        term = q.strip()
        if len(term) < MIN_TERM:
            return await self.recent_cards(principal) if kind == "todo" else []
        kinds: Sequence[str] = LINK_KINDS if kind == "all" else (kind,)
        per_kind = [
            await self._kind_targets(current, term, principal, exclude_card_id) for current in kinds
        ]
        return [target for targets in per_kind for target in targets]

    async def _kind_targets(
        self,
        kind: str,
        term: str,
        principal: Principal,
        exclude_card_id: uuid.UUID | None,
    ) -> list[TodoLinkTarget]:
        """The readable targets of one kind that match ``term``, in candidate order."""
        ids = await self._candidates(kind, term, principal, exclude_card_id)
        return await self._as_targets(kind, ids, principal)

    async def _as_targets(
        self, kind: str, ids: Sequence[uuid.UUID], principal: Principal
    ) -> list[TodoLinkTarget]:
        """The readable ones of ``ids`` as link targets, in the given order."""
        resolved = await self.resolve([(kind, i) for i in ids], principal, grants=False)
        return [
            TodoLinkTarget(
                kind=kind,  # type: ignore[arg-type]
                target_id=i,
                title=r.title or "",
                detail=r.detail or TodoLinkDetail(),
            )
            for i in ids
            if (r := resolved[(kind, i)]).accessible
        ]

    async def _candidates(
        self,
        kind: str,
        term: str,
        principal: Principal,
        exclude_card_id: uuid.UUID | None,
    ) -> list[uuid.UUID]:
        pattern = f"%{escape_like(term)}%"
        match kind:
            case "application":
                return await self._application_candidates(term, principal)
            case "meeting":
                return await self._meeting_candidates(pattern, principal)
            case "agenda_item":
                return await self._agenda_candidates(pattern, principal)
            case "vote":
                return await self._vote_candidates(term, principal)
            case "appointment":
                return await self._appointment_candidates(pattern, principal)
            case "gremium":
                return await self._gremium_candidates(term, principal)
            case "invoice":
                return await self._invoice_candidates(term, principal)
            case "expense":
                return await self._expense_candidates(term, principal)
            case "budget":
                return await self._budget_candidates(pattern, principal)
            case "ticket":
                return await self._ticket_candidates(term, principal)
            case _:
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
        scope = await self._meeting_scope_condition(principal)
        stmt = (
            select(Meeting.id)
            .where(Meeting.title.ilike(pattern, escape="\\"), *_present(scope))
            .order_by(Meeting.date.desc().nulls_last(), Meeting.id)
            .limit(PER_KIND)
        )
        return list((await self.session.scalars(stmt)).all())

    async def _agenda_candidates(self, pattern: str, principal: Principal) -> list[uuid.UUID]:
        app_title = cast(Application.data["title"].astext, String)
        scope = await self._meeting_scope_condition(principal)
        stmt = (
            select(MeetingAgendaItem.id)
            .join(Meeting, Meeting.id == MeetingAgendaItem.meeting_id)
            .outerjoin(Application, Application.id == MeetingAgendaItem.application_id)
            .where(
                or_(
                    MeetingAgendaItem.title.ilike(pattern, escape="\\"),
                    app_title.ilike(pattern, escape="\\"),
                    Meeting.title.ilike(pattern, escape="\\"),
                ),
                *_present(scope),
            )
            .order_by(
                Meeting.date.desc().nulls_last(),
                MeetingAgendaItem.position,
                MeetingAgendaItem.id,
            )
            .limit(PER_KIND)
        )
        return list((await self.session.scalars(stmt)).all())

    async def _vote_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """Reuses ``voting.listing.list_votes`` (``GET /votes``), with every status."""
        from app.modules.voting.listing import list_votes

        page = await list_votes(
            self.session, principal, statuses=VOTE_STATUSES, q=term, limit=PER_KIND, offset=0
        )
        return [v.id for v in page.items]

    async def _appointment_candidates(self, pattern: str, principal: Principal) -> list[uuid.UUID]:
        """The readable Termine by title or place, the newest first."""
        service = AppointmentService(self.session)
        found = await service.matching(await service.viewer(principal), pattern, PER_KIND)
        return [item.row.id for item in found]

    async def _gremium_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """The trigram match of the search source on name and slug, in the Gremien scope."""
        visible = await self._gremien_scope(principal)
        if visible is not None and not visible:
            return []
        where, rank = trigram_rank(
            term, [Gremium.name, Gremium.slug], dialect=dialect_of(self.session)
        )
        in_scope = (Gremium.id.in_(visible),) if visible is not None else ()
        stmt = (
            select(Gremium.id)
            .where(where, *in_scope)
            .order_by(rank.desc(), Gremium.name, Gremium.id)
            .limit(PER_KIND)
        )
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

    async def _budget_candidates(self, pattern: str, principal: Principal) -> list[uuid.UUID]:
        """Cost centres by name or path key, behind the gate of the budget pages."""
        if not has_budget_read(principal):
            return []
        stmt = (
            select(Budget.id)
            .where(
                or_(
                    Budget.name.ilike(pattern, escape="\\"),
                    Budget.path_key.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Budget.path_key, Budget.id)
            .limit(PER_KIND)
        )
        return list((await self.session.scalars(stmt)).all())

    async def _ticket_candidates(self, term: str, principal: Principal) -> list[uuid.UUID]:
        """Reuses ``TicketService.list``, behind ``ticket.manage`` like ``GET /tickets``."""
        if not principal.has(TICKET_MANAGE):
            return []
        from app.modules.tickets.service import TicketService

        page = await TicketService(self.session).list(q=term, limit=PER_KIND)
        return [t.id for t in page.items]

    async def recent_cards(self, principal: Principal) -> list[TodoLinkTarget]:
        """The newest readable open cards, ``RECENT_CARDS`` at most, as link targets."""
        scope = await self.access.scope(principal)
        ids = list(
            (
                await self.session.scalars(
                    select(TodoCard.id)
                    .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                    .where(scope.condition(), TodoCard.archived_at.is_(None))
                    .order_by(TodoCard.updated_at.desc(), TodoCard.id)
                    .limit(RECENT_CARDS)
                )
            ).all()
        )
        return await self._as_targets("todo", ids, principal)

    async def _todo_candidates(
        self, pattern: str, principal: Principal, exclude_card_id: uuid.UUID | None
    ) -> list[uuid.UUID]:
        scope = await self.access.scope(principal)
        others = (TodoCard.id != exclude_card_id,) if exclude_card_id is not None else ()
        stmt = (
            select(TodoCard.id)
            .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
            .where(
                scope.condition(),
                TodoCard.archived_at.is_(None),
                TodoCard.title.ilike(pattern, escape="\\"),
                *others,
            )
            .order_by(TodoCard.updated_at.desc(), TodoCard.id)
            .limit(PER_KIND)
        )
        return list((await self.session.scalars(stmt)).all())
