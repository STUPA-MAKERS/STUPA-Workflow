"""The reads of the graph: the relations, the ids of each kind and the facts of a node.

A relation is a link of the table ``link`` or a relation that the data model holds
(spec 001424). The facts are the date and the Gremien of an element, which the filters
"Zeitraum" and "Gremium" use (spec 001425). The reads apply no read rule: the service
resolves every element for the reader before it shows one.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, null, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, ApplicationLink
from app.modules.budget.tree_models import Budget, BudgetExpense, Invoice
from app.modules.calendar.models import Appointment, Invitation
from app.modules.graph.build import Ref, Relation
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.tickets.models import Ticket
from app.modules.todos.grouping import grouped
from app.modules.todos.models import Link, TodoBoard, TodoCard
from app.modules.voting.models import Vote

#: A built-in relation: the kinds of its two ends and the read of their ids. A row with a
#: missing end is no relation.
Builtin = tuple[str, str, Select[Any, Any]]


def builtin_reads() -> tuple[Builtin, ...]:
    """The built-in relations of spec 001424, one read each.

    A vote with a TOP has no relation to the meeting, because the TOP already connects
    the two.
    """
    item = MeetingAgendaItem
    return (
        (
            "application",
            "application",
            select(ApplicationLink.application_id, ApplicationLink.predecessor_id),
        ),
        ("application", "agenda_item", select(item.application_id, item.id)),
        ("application", "vote", select(Vote.application_id, Vote.id)),
        ("application", "budget", select(Application.id, Application.budget_id)),
        ("application", "expense", select(BudgetExpense.application_id, BudgetExpense.id)),
        ("meeting", "agenda_item", select(item.meeting_id, item.id)),
        ("meeting", "gremium", select(Meeting.id, Meeting.gremium_id)),
        ("meeting", "vote", select(Vote.meeting_id, Vote.id).where(Vote.agenda_item_id.is_(None))),
        ("agenda_item", "vote", select(Vote.agenda_item_id, Vote.id)),
        ("agenda_item", "todo", select(item.id, item.todo_id)),
        ("invoice", "expense", select(BudgetExpense.invoice_id, BudgetExpense.id)),
        ("expense", "budget", select(BudgetExpense.id, BudgetExpense.budget_id)),
        ("appointment", "gremium", select(Invitation.appointment_id, Invitation.gremium_id)),
    )


async def link_relations(session: AsyncSession, kinds: Collection[str]) -> list[Relation]:
    """The links between two elements of ``kinds``."""
    rows = (
        await session.execute(
            select(Link.a_kind, Link.a_id, Link.b_kind, Link.b_id).where(
                Link.a_kind.in_(list(kinds)), Link.b_kind.in_(list(kinds))
            )
        )
    ).all()
    return [
        Relation(a=(a_kind, a_id), b=(b_kind, b_id), source="link")
        for a_kind, a_id, b_kind, b_id in rows
    ]


async def builtin_relations(session: AsyncSession, kinds: Collection[str]) -> list[Relation]:
    """The built-in relations between two elements of ``kinds``."""
    found = [
        (a_kind, b_kind, (await session.execute(stmt)).all())
        for a_kind, b_kind, stmt in builtin_reads()
        if a_kind in kinds and b_kind in kinds
    ]
    return [
        Relation(a=(a_kind, a_id), b=(b_kind, b_id), source="builtin")
        for a_kind, b_kind, rows in found
        for a_id, b_id in rows
        if a_id is not None and b_id is not None
    ]


def _id_reads() -> Mapping[str, Select[Any]]:
    """The ids of every element of a kind; an archived card is not an element."""
    return {
        "application": select(Application.id),
        "meeting": select(Meeting.id),
        "agenda_item": select(MeetingAgendaItem.id),
        "vote": select(Vote.id),
        "appointment": select(Appointment.id),
        "gremium": select(Gremium.id),
        "invoice": select(Invoice.id),
        "expense": select(BudgetExpense.id),
        "budget": select(Budget.id),
        "ticket": select(Ticket.id),
        "todo": select(TodoCard.id).where(TodoCard.archived_at.is_(None)),
    }


async def all_refs(session: AsyncSession, kinds: Collection[str]) -> frozenset[Ref]:
    """Every element of ``kinds``, for the switch "Auch ohne Verknüpfung" (spec 001423)."""
    found = [
        (kind, (await session.scalars(stmt)).all())
        for kind, stmt in _id_reads().items()
        if kind in kinds
    ]
    return frozenset((kind, element_id) for kind, ids in found for element_id in ids)


def _fact_read(kind: str, ids: Collection[uuid.UUID]) -> Select[Any, Any, Any, Any]:
    """The read ``(id, date, fallback date, gremium)`` of the elements of one kind.

    The date of a node (spec 001425): the date of a meeting and of its TOPs, the start of
    a Termin, the invoice date of an invoice and of a Buchung, the due date of a card,
    and else the creation. A Gremium and a cost centre have no date.
    """
    wanted = list(ids)
    none = null()
    match kind:
        case "application":
            return select(
                Application.id, Application.created_at, none, Application.gremium_id
            ).where(Application.id.in_(wanted))
        case "meeting":
            return select(Meeting.id, Meeting.date, none, Meeting.gremium_id).where(
                Meeting.id.in_(wanted)
            )
        case "agenda_item":
            return (
                select(MeetingAgendaItem.id, Meeting.date, none, Meeting.gremium_id)
                .join(Meeting, Meeting.id == MeetingAgendaItem.meeting_id)
                .where(MeetingAgendaItem.id.in_(wanted))
            )
        case "vote":
            return select(Vote.id, Vote.created_at, none, Vote.eligible_group).where(
                Vote.id.in_(wanted)
            )
        case "appointment":
            return (
                select(Appointment.id, Appointment.starts_on, none, Invitation.gremium_id)
                .outerjoin(Invitation, Invitation.appointment_id == Appointment.id)
                .where(Appointment.id.in_(wanted))
            )
        case "gremium":
            return select(Gremium.id, none, none, Gremium.id).where(Gremium.id.in_(wanted))
        case "invoice":
            return select(Invoice.id, Invoice.issue_date, Invoice.created_at, none).where(
                Invoice.id.in_(wanted)
            )
        case "expense":
            return (
                select(
                    BudgetExpense.id,
                    BudgetExpense.invoice_date,
                    BudgetExpense.created_at,
                    Budget.gremium_id,
                )
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .where(BudgetExpense.id.in_(wanted))
            )
        case "budget":
            return select(Budget.id, none, none, Budget.gremium_id).where(Budget.id.in_(wanted))
        case "ticket":
            return select(Ticket.id, Ticket.created_at, none, none).where(Ticket.id.in_(wanted))
        case "todo":
            return (
                select(TodoCard.id, TodoCard.due_date, TodoCard.created_at, TodoBoard.gremium_id)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .where(TodoCard.id.in_(wanted))
            )
        case _:
            raise ValueError(f"unknown kind: {kind}")


def as_date(value: object) -> date | None:
    """A date column or a timestamp column as a date."""
    match value:
        case datetime():
            return value.date()
        case date():
            return value
        case _:
            return None


def as_gremium(value: object) -> uuid.UUID | None:
    """A Gremium column as an id; the Gremium of a vote is text and can be no id."""
    match value:
        case uuid.UUID():
            return value
        case str():
            try:
                return uuid.UUID(value)
            except ValueError:
                return None
        case _:
            return None


Fact = tuple[date | None, frozenset[uuid.UUID]]


async def facts(
    session: AsyncSession, by_kind: Mapping[str, Collection[uuid.UUID]]
) -> dict[Ref, Fact]:
    """The date and the Gremien of each element; a Termin has one Gremium per invitation."""
    found = [
        (kind, (await session.execute(_fact_read(kind, ids))).all())
        for kind, ids in by_kind.items()
        if ids
    ]
    rows = [
        ((kind, element_id), as_date(first) or as_date(second), as_gremium(gremium))
        for kind, kind_rows in found
        for element_id, first, second, gremium in kind_rows
    ]
    gremien = grouped((ref, g) for ref, _, g in rows if g is not None)
    return {ref: (when, frozenset(gremien.get(ref, ()))) for ref, when, _ in rows}
