"""The automatic bookings of pretix and Mollie, each in its own savepoint.

A booking names `Pretix` or `Mollie` as its author: the actor of the booking and of its
audit entry (§F/integrations/pretix/003086, §F/integrations/mollie/003097, 003103). A
booking of an Event links the Event (§F/collaboration/events/003033), and the link names
the person who linked the pretix event, else the creator of the Event, because a link
needs an account. A booking that the platform cannot make, for example in a closed fiscal
year, rolls back its savepoint and gives the problem code as its cause; the caller keeps
it for the admin page and tries again at the next run.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import ExpenseCreate, SubBookingCreate
from app.modules.todos.models import Link
from app.shared.errors import AppError

Author = Literal["Pretix", "Mollie"]
Kind = Literal["income", "expense"]

#: The cause of a booking of an Event whose link and Event name no account.
NO_ACTOR = "no_actor"
#: The cause of a booking whose values the budget refuses, for example a sum too large.
INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class Part:
    """One sub-booking of a booking: its amount, its text and the Event it links."""

    amount: Decimal
    text: str
    event: tuple[uuid.UUID, uuid.UUID] | None


@dataclass(frozen=True, slots=True)
class Entry:
    """One booking that a run asks for.

    Attributes:
        author: `Pretix` or `Mollie`.
        kind: `income` or `expense`.
        budget_id: The cost centre.
        amount: The sum, above zero. A booking with parts gets the sum of its parts.
        on: The day of the payment.
        text: The description.
        reference: The code of the order or the id of Mollie.
        event: The Event and the account of the link, else None.
        parts: The sub-bookings, each with its own Event (003097).
    """

    author: Author
    kind: Kind
    budget_id: uuid.UUID
    amount: Decimal
    on: date | None
    text: str
    reference: str
    event: tuple[uuid.UUID, uuid.UUID] | None = None
    parts: Sequence[Part] = ()


def _link(expense_id: uuid.UUID, event: tuple[uuid.UUID, uuid.UUID]) -> Link:
    event_id, actor = event
    return Link.between(("event", event_id), ("expense", expense_id), actor)


async def _make(session: AsyncSession, entry: Entry) -> uuid.UUID:
    service = BudgetTreeService(session, actor=entry.author)
    booked = await service.book_expense(
        ExpenseCreate(
            amount=entry.amount,
            description=entry.text,
            kind=entry.kind,
            budgetId=entry.budget_id,
            paymentDate=entry.on,
            referenceNumber=entry.reference,
        ),
        actor=entry.author,
        commit=False,
    )
    children = [
        await service.create_sub_booking(
            booked.id,
            SubBookingCreate(
                amount=part.amount,
                description=part.text,
                paymentDate=entry.on,
                referenceNumber=entry.reference,
            ),
            actor=entry.author,
            commit=False,
        )
        for part in entry.parts
    ]
    links = ([_link(booked.id, entry.event)] if entry.event is not None else []) + [
        _link(child.id, part.event)
        for child, part in zip(children, entry.parts, strict=True)
        if part.event is not None
    ]
    session.add_all(links)
    await session.flush()
    return booked.id


async def book(session: AsyncSession, entry: Entry) -> uuid.UUID | str:
    """Make one booking in a savepoint; return its id, or the cause of its failure."""
    try:
        async with session.begin_nested():
            return await _make(session, entry)
    except AppError as exc:
        return exc.code
    except ValueError:
        return INVALID
