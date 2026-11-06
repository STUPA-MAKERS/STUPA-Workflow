"""Events (``Veranstaltung``): the event data of a card, its totals, decisions and series.

A card with a ``todo_card_event`` row is an Event. Its links bring the money and the
decisions:

* Totals: the requested and approved amounts of the linked Anträge, and the expenses
  and the income of the linked Buchungen. A sub-booking whose parent is linked too
  counts once, through the parent. The totals count every linked element, because
  each reader of the Event reads them (spec 000479).
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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, ApplicationDecision
from app.modules.applications.service.service_base import _title_of
from app.modules.budget.tree_models import BudgetExpense
from app.modules.livevote.models import Meeting, MeetingAgendaItem
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


@dataclass
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


@dataclass
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
    out = {card_id: Totals() for card_id in card_ids}
    if not card_ids:
        return out
    links = await _links(session, card_ids, "application", "expense")
    apps_of: dict[uuid.UUID, set[uuid.UUID]] = {}
    expenses_of: dict[uuid.UUID, set[uuid.UUID]] = {}
    for link in links:
        if link.application_id is not None:
            apps_of.setdefault(link.card_id, set()).add(link.application_id)
        if link.expense_id is not None:
            expenses_of.setdefault(link.card_id, set()).add(link.expense_id)
    app_ids = {aid for ids in apps_of.values() for aid in ids}
    if app_ids:
        rows = await session.execute(
            select(Application.id, Application.amount, ApplicationDecision.approved_amount)
            .outerjoin(
                ApplicationDecision,
                and_(
                    ApplicationDecision.application_id == Application.id,
                    ApplicationDecision.superseded_at.is_(None),
                ),
            )
            .where(Application.id.in_(app_ids))
        )
        money: dict[uuid.UUID, tuple[Decimal, Decimal | None]] = {}
        decided: set[uuid.UUID] = set()
        for app_id, amount, approved in rows.tuples().all():
            money[app_id] = (amount or _ZERO, approved)
        decided_rows = await session.scalars(
            select(ApplicationDecision.application_id).where(
                ApplicationDecision.application_id.in_(app_ids),
                ApplicationDecision.superseded_at.is_(None),
            )
        )
        decided = set(decided_rows.all())
        for card_id, ids in apps_of.items():
            for app_id in ids:
                amount, approved = money.get(app_id, (_ZERO, None))
                out[card_id].requested += amount
                if app_id in decided:
                    out[card_id].approved += approved if approved is not None else amount
    expense_ids = {eid for ids in expenses_of.values() for eid in ids}
    if expense_ids:
        rows = await session.execute(
            select(
                BudgetExpense.id,
                BudgetExpense.kind,
                BudgetExpense.amount,
                BudgetExpense.parent_expense_id,
            ).where(BudgetExpense.id.in_(expense_ids))
        )
        facts = {eid: (kind, amount, parent) for eid, kind, amount, parent in rows.tuples().all()}
        for card_id, ids in expenses_of.items():
            for eid in ids:
                if eid not in facts:
                    continue
                kind, amount, parent = facts[eid]
                if parent is not None and parent in ids:
                    continue
                if kind == "income":
                    out[card_id].income += amount
                else:
                    out[card_id].expenses += amount
    return out


async def decisions(session: AsyncSession, card_id: uuid.UUID) -> list[Decision]:
    """The decisions of an Event: valid decisions of Anträge, closed votes of TOPs/votes."""
    links = await _links(session, [card_id], "application", "agenda_item", "vote")
    app_ids = {link.application_id for link in links if link.application_id is not None}
    item_ids = {link.agenda_item_id for link in links if link.agenda_item_id is not None}
    vote_ids = {link.vote_id for link in links if link.vote_id is not None}
    out: list[Decision] = []
    seen_votes: set[uuid.UUID] = set()
    if app_ids:
        rows = await session.execute(
            select(Application, ApplicationDecision, Meeting.title)
            .join(ApplicationDecision, ApplicationDecision.application_id == Application.id)
            .outerjoin(Vote, Vote.id == ApplicationDecision.vote_id)
            .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
            .where(
                Application.id.in_(app_ids),
                ApplicationDecision.superseded_at.is_(None),
            )
        )
        for app, decision, meeting_title in rows.tuples().all():
            if decision.vote_id is not None:
                seen_votes.add(decision.vote_id)
            out.append(
                Decision(
                    kind="decision",
                    title=_title_of(app.data) or "",
                    decided_at=decision.decided_at,
                    meeting_title=meeting_title,
                    result="passed",
                    amount=(
                        decision.approved_amount
                        if decision.approved_amount is not None
                        else app.amount
                    ),
                    conditions=list(decision.conditions or []),
                    target_id=app.id,
                )
            )
    conditions: list[ColumnElement[bool]] = []
    if item_ids:
        conditions.append(Vote.agenda_item_id.in_(item_ids))
    if vote_ids:
        conditions.append(Vote.id.in_(vote_ids))
    if conditions:
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
        )
        titles = await _application_titles(
            session, {vote.application_id for vote, _m, _t in vote_rows if vote.application_id}
        )
        for vote, meeting_title, item_title in vote_rows:
            if vote.id in seen_votes:
                continue
            seen_votes.add(vote.id)
            title = (
                vote.question
                or (titles.get(vote.application_id) if vote.application_id else None)
                or item_title
                or ""
            )
            out.append(
                Decision(
                    kind="vote",
                    title=title,
                    decided_at=vote.closed_at,
                    meeting_title=meeting_title,
                    result=vote.result,
                    amount=None,
                    target_id=vote.id,
                )
            )
    oldest = datetime.min.replace(tzinfo=UTC)
    out.sort(key=lambda d: d.decided_at or oldest, reverse=True)
    return out


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
    by_kind: dict[str, set[uuid.UUID]] = {}
    for kind, target_id in refs:
        if kind in ONE_EVENT_KINDS:
            by_kind.setdefault(kind, set()).add(target_id)
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
