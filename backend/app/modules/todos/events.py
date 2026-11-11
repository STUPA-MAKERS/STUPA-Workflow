"""Events (``Veranstaltung``): the event data of a card, its totals, decisions and series.

A card with a ``todo_card_event`` row is an Event. Its links bring the money and the
decisions:

* Totals: the requested amount of the linked Anträge, the approved amount of those in an
  approved state (spec 000572), and the expenses and the income of the linked Buchungen.
  A sub-booking whose parent is linked too counts once, through the parent. The totals
  count every linked element, because each reader of the Event reads them (spec 000479).
* Decisions: the valid decision of each linked Antrag and each closed vote of a linked
  TOP or vote, the newest first. A vote that made the decision of a linked Antrag shows
  once, as that decision (spec 000482).
* One Event per element: an Antrag, a Buchung or an invoice is linked to at most one
  Event (spec 000481, 409 ``event_link_taken``).
* Series: the other Events of the series that the viewer reads, the newest first, and
  the number of the others (spec 000483).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, ApplicationDecision
from app.modules.applications.service.service_base import _title_of
from app.modules.budget.tree_models import BudgetExpense
from app.modules.flow.models import State
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.todos.grouping import grouped
from app.modules.todos.models import (
    LINK_COLUMNS,
    TodoBoard,
    TodoCard,
    TodoCardEvent,
    TodoEventSeries,
    TodoLink,
)
from app.modules.voting.models import Vote
from app.shared.errors import ConflictError

#: The link kinds that belong to at most one Event.
ONE_EVENT_KINDS: tuple[str, ...] = ("application", "expense", "invoice")
_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class Totals:
    """The money of one Event."""

    requested: Decimal = _ZERO
    approved: Decimal = _ZERO
    expenses: Decimal = _ZERO
    income: Decimal = _ZERO

    @property
    def balance(self) -> Decimal:
        """Income minus expenses."""
        return self.income - self.expenses


@dataclass(frozen=True, slots=True)
class Decision:
    """One row of the decisions of an Event."""

    kind: str
    title: str
    decided_at: datetime | None
    meeting_title: str | None
    result: str | None
    amount: Decimal | None
    conditions: list[str] = field(default_factory=list)
    target_id: uuid.UUID | None = None


async def event_rows(
    session: AsyncSession, card_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, TodoCardEvent]:
    """The event rows of the cards that are Events."""
    ids = list(card_ids)
    if not ids:
        return {}
    rows = (
        await session.scalars(select(TodoCardEvent).where(TodoCardEvent.card_id.in_(ids)))
    ).all()
    return {row.card_id: row for row in rows}


async def series_names(
    session: AsyncSession, series_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    """The names of the series."""
    ids = {sid for sid in series_ids if sid is not None}
    if not ids:
        return {}
    rows = await session.execute(
        select(TodoEventSeries.id, TodoEventSeries.name).where(TodoEventSeries.id.in_(ids))
    )
    return dict(rows.tuples().all())


async def _links(
    session: AsyncSession, card_ids: Sequence[uuid.UUID], *kinds: str
) -> list[TodoLink]:
    return list(
        (
            await session.scalars(
                select(TodoLink).where(
                    TodoLink.card_id.in_(card_ids),
                    or_(*(getattr(TodoLink, LINK_COLUMNS[kind]).isnot(None) for kind in kinds)),
                )
            )
        ).all()
    )


async def totals(session: AsyncSession, card_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Totals]:
    """The totals of each card, also for a card without links (all zero)."""
    if not card_ids:
        return {}
    links = await _links(session, card_ids, "application", "expense")
    apps_of = _id_sets(
        (link.card_id, link.application_id) for link in links if link.application_id is not None
    )
    expenses_of = _id_sets(
        (link.card_id, link.expense_id) for link in links if link.expense_id is not None
    )
    money, approved = await _application_money(
        session, frozenset(aid for ids in apps_of.values() for aid in ids)
    )
    bookings = await _bookings(
        session, frozenset(eid for ids in expenses_of.values() for eid in ids)
    )
    return {
        card_id: _card_totals(
            apps_of.get(card_id, frozenset()),
            _counted(expenses_of.get(card_id, frozenset()), bookings),
            money,
            approved,
        )
        for card_id in card_ids
    }


type _Money = Mapping[uuid.UUID, tuple[Decimal, Decimal | None]]
type _Booking = tuple[str, Decimal, uuid.UUID | None]


def _id_sets(
    pairs: Iterable[tuple[uuid.UUID, uuid.UUID]],
) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    """Group the target ids of the links by their card."""
    return {card_id: frozenset(ids) for card_id, ids in grouped(pairs).items()}


async def _application_money(
    session: AsyncSession, app_ids: frozenset[uuid.UUID]
) -> tuple[_Money, frozenset[uuid.UUID]]:
    """The requested and decided amount of each Antrag, and the Anträge in an approved state.

    The approved state is the flag ``is_approved`` of the current state (spec 000572).
    """
    if not app_ids:
        return {}, frozenset()
    rows = await session.execute(
        select(
            Application.id,
            Application.amount,
            ApplicationDecision.approved_amount,
            State.is_approved,
        )
        .outerjoin(
            ApplicationDecision,
            and_(
                ApplicationDecision.application_id == Application.id,
                ApplicationDecision.superseded_at.is_(None),
            ),
        )
        .outerjoin(State, State.id == Application.current_state_id)
        .where(Application.id.in_(app_ids))
    )
    found = rows.tuples().all()
    money = {app_id: (amount or _ZERO, approved) for app_id, amount, approved, _flag in found}
    return money, frozenset(app_id for app_id, _amount, _approved, flag in found if flag)


async def _bookings(
    session: AsyncSession, expense_ids: frozenset[uuid.UUID]
) -> Mapping[uuid.UUID, _Booking]:
    """The kind, the amount and the parent of each Buchung."""
    if not expense_ids:
        return {}
    rows = await session.execute(
        select(
            BudgetExpense.id,
            BudgetExpense.kind,
            BudgetExpense.amount,
            BudgetExpense.parent_expense_id,
        ).where(BudgetExpense.id.in_(expense_ids))
    )
    return {eid: (kind, amount, parent) for eid, kind, amount, parent in rows.tuples().all()}


def _counted(
    ids: frozenset[uuid.UUID], bookings: Mapping[uuid.UUID, _Booking]
) -> tuple[tuple[str, Decimal], ...]:
    """The kind and the amount of each linked Buchung that counts.

    A sub-booking whose parent is linked too counts once, through the parent.
    """
    known = (bookings[eid] for eid in ids if eid in bookings)
    return tuple(
        (kind, amount) for kind, amount, parent in known if parent is None or parent not in ids
    )


def _card_totals(
    app_ids: frozenset[uuid.UUID],
    booked: Iterable[tuple[str, Decimal]],
    money: _Money,
    in_approved_state: frozenset[uuid.UUID],
) -> Totals:
    """The totals of one card from the money of its Anträge and its counted Buchungen.

    ``approved`` counts each Antrag in an approved state: the amount of its valid decision,
    else the requested amount (spec 000572).
    """
    amounts = {app_id: money.get(app_id, (_ZERO, None)) for app_id in app_ids}
    entries = tuple(booked)
    return Totals(
        requested=sum((amount for amount, _approved in amounts.values()), _ZERO),
        approved=sum(
            (
                approved if approved is not None else amount
                for app_id, (amount, approved) in amounts.items()
                if app_id in in_approved_state
            ),
            _ZERO,
        ),
        expenses=sum((amount for kind, amount in entries if kind != "income"), _ZERO),
        income=sum((amount for kind, amount in entries if kind == "income"), _ZERO),
    )


async def decisions(session: AsyncSession, card_id: uuid.UUID) -> list[Decision]:
    """The decisions of an Event: valid decisions of Anträge, closed votes of TOPs/votes."""
    links = await _links(session, [card_id], "application", "agenda_item", "vote")
    app_ids = {link.application_id for link in links if link.application_id is not None}
    item_ids = {link.agenda_item_id for link in links if link.agenda_item_id is not None}
    vote_ids = {link.vote_id for link in links if link.vote_id is not None}
    app_rows = (
        (
            await session.execute(
                select(Application, ApplicationDecision, Meeting.title)
                .join(ApplicationDecision, ApplicationDecision.application_id == Application.id)
                .outerjoin(Vote, Vote.id == ApplicationDecision.vote_id)
                .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
                .where(
                    Application.id.in_(app_ids),
                    ApplicationDecision.superseded_at.is_(None),
                )
            )
        )
        .tuples()
        .all()
        if app_ids
        else ()
    )
    conditions = (
        *((Vote.agenda_item_id.in_(item_ids),) if item_ids else ()),
        *((Vote.id.in_(vote_ids),) if vote_ids else ()),
    )
    vote_rows = (
        (
            await session.execute(
                select(Vote, Meeting.title, MeetingAgendaItem.title)
                .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
                .outerjoin(MeetingAgendaItem, MeetingAgendaItem.id == Vote.agenda_item_id)
                .where(or_(*conditions), Vote.status == "closed")
            )
        )
        .tuples()
        .all()
        if conditions
        else ()
    )
    titles = await _application_titles(
        session, {vote.application_id for vote, _m, _t in vote_rows if vote.application_id}
    )
    seen = frozenset(d.vote_id for _app, d, _m in app_rows if d.vote_id is not None)
    first = {vote.id: index for index, (vote, _m, _t) in reversed(tuple(enumerate(vote_rows)))}
    fresh = (
        row
        for index, row in enumerate(vote_rows)
        if first[row[0].id] == index and row[0].id not in seen
    )
    found = (
        *(_app_decision(app, decision, meeting) for app, decision, meeting in app_rows),
        *(_vote_decision(vote, meeting, item, titles) for vote, meeting, item in fresh),
    )
    oldest = datetime.min.replace(tzinfo=UTC)
    return sorted(found, key=lambda d: d.decided_at or oldest, reverse=True)


def _app_decision(
    app: Application, decision: ApplicationDecision, meeting_title: str | None
) -> Decision:
    """The valid decision of a linked Antrag."""
    return Decision(
        kind="decision",
        title=_title_of(app.data) or "",
        decided_at=decision.decided_at,
        meeting_title=meeting_title,
        result="passed",
        amount=(decision.approved_amount if decision.approved_amount is not None else app.amount),
        conditions=list(decision.conditions or []),
        target_id=app.id,
    )


def _vote_decision(
    vote: Vote,
    meeting_title: str | None,
    item_title: str | None,
    titles: Mapping[uuid.UUID, str],
) -> Decision:
    """A closed vote of a linked TOP or vote, titled by its question, Antrag or TOP."""
    title = (
        vote.question
        or (titles.get(vote.application_id) if vote.application_id else None)
        or item_title
        or ""
    )
    return Decision(
        kind="vote",
        title=title,
        decided_at=vote.closed_at,
        meeting_title=meeting_title,
        result=vote.result,
        amount=None,
        target_id=vote.id,
    )


async def _application_titles(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Application.id, Application.data).where(Application.id.in_(ids))
    )
    return {aid: _title_of(data) or "" for aid, data in rows.tuples().all()}


async def editions(
    session: AsyncSession,
    card: TodoCard,
    series_id: uuid.UUID | None,
    readable: ColumnElement[bool],
) -> tuple[list[tuple[TodoCard, TodoBoard, TodoCardEvent]], int]:
    """The other Events of the series that the viewer reads, newest first, and the rest."""
    if series_id is None:
        return [], 0
    base = (
        select(TodoCard, TodoBoard, TodoCardEvent)
        .join(TodoCardEvent, TodoCardEvent.card_id == TodoCard.id)
        .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
        .where(TodoCardEvent.series_id == series_id, TodoCard.id != card.id)
    )
    total = await session.scalar(
        select(func.count()).select_from(base.with_only_columns(TodoCard.id).subquery())
    )
    rows = (
        (
            await session.execute(
                base.where(readable).order_by(
                    TodoCardEvent.starts_on.desc().nulls_last(), TodoCard.created_at.desc()
                )
            )
        )
        .tuples()
        .all()
    )
    return list(rows), max(0, int(total or 0) - len(rows))


async def check_one_event(
    session: AsyncSession,
    card_id: uuid.UUID,
    refs: Iterable[tuple[str, uuid.UUID]],
) -> None:
    """Refuse a link of an Antrag, a Buchung or an invoice that another Event has.

    Raises:
        ConflictError: ``event_link_taken`` (HTTP 409).
    """
    by_kind = {
        kind: frozenset(ids)
        for kind, ids in grouped(
            (kind, target_id) for kind, target_id in refs if kind in ONE_EVENT_KINDS
        ).items()
    }
    if not by_kind:
        return
    conditions = [getattr(TodoLink, LINK_COLUMNS[kind]).in_(ids) for kind, ids in by_kind.items()]
    taken = await session.scalar(
        select(TodoLink.id)
        .join(TodoCardEvent, TodoCardEvent.card_id == TodoLink.card_id)
        .where(or_(*conditions), TodoLink.card_id != card_id)
        .limit(1)
    )
    if taken is not None:
        raise ConflictError(
            "The element belongs to another Veranstaltung.", code="event_link_taken"
        )


def balance_text(value: Decimal) -> str:
    """The amount as a plain decimal string with two places."""
    return f"{value.quantize(Decimal('0.01'))}"
