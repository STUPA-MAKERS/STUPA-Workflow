"""The read of the pretix sales and the bookings of the paid orders.

`sync_link` reads the orders of one linked pretix event once, stores the sales while the
part `Verkaufszahlen zeigen` is on (§F/integrations/pretix/003084, 003085) and books each
new paid order and refund while the part `Einnahmen buchen` is on and the Event has its
field `Einnahmen-Kostenstelle` (003086). A failed read keeps the last sales and their time.
Without a part that is on, the run calls pretix not at all (003082).

No function here commits. The worker and the router own the transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.event_sales.booking import NO_ACTOR, Entry, book
from app.modules.event_sales.outcome import Failure, Outcome, joined
from app.modules.events.models import Event
from app.modules.pretix.client import PretixClient, PretixError
from app.modules.pretix.connection import part_on
from app.modules.pretix.models import PretixBooking, PretixEventLink, PretixSettings
from app.modules.pretix.rules import Candidate, candidates, sales_of
from app.modules.statuses.service import in_phase

#: The days after its end during which the worker still reads an Event (003085).
AFTER_END_DAYS = 30


async def active_links(session: AsyncSession, today: date) -> Sequence[PretixEventLink]:
    """Return the links of the Events in the phase `open` or that ended at most 30 days ago."""
    last_day = func.coalesce(Event.ends_on, Event.starts_on)
    return (
        await session.scalars(
            select(PretixEventLink)
            .join(Event, Event.id == PretixEventLink.event_id)
            .where(
                or_(
                    in_phase(Event.status, "event", "open"),
                    last_day >= today - timedelta(days=AFTER_END_DAYS),
                )
            )
            .order_by(PretixEventLink.created_at)
        )
    ).all()


async def link_actor(session: AsyncSession, link: PretixEventLink) -> uuid.UUID | None:
    """The account of the links of a booking: who linked the pretix event, else the creator."""
    if link.created_by is not None:
        return link.created_by
    return await session.scalar(select(Event.created_by).where(Event.id == link.event_id))


async def _done(session: AsyncSession, slug: str) -> frozenset[tuple[str, str]]:
    rows = await session.execute(
        select(PretixBooking.source, PretixBooking.source_key).where(
            PretixBooking.slug == slug, PretixBooking.state == "booked"
        )
    )
    return frozenset((source, key) for source, key in rows.all())


async def _record(
    session: AsyncSession, slug: str, candidate: Candidate, result: uuid.UUID | str
) -> None:
    booked = isinstance(result, uuid.UUID)
    values = {
        "state": "booked" if booked else "failed",
        "expense_id": result if booked else None,
        "error": None if booked else result,
    }
    await session.execute(
        pg_insert(PretixBooking)
        .values(
            id=uuid.uuid4(), slug=slug, source=candidate.source, source_key=candidate.key, **values
        )
        .on_conflict_do_update(constraint="uq_pretix_booking_source", set_=values)
    )


def _entry(
    link: PretixEventLink, candidate: Candidate, actor: uuid.UUID, budget: uuid.UUID
) -> Entry:
    suffix = " (Erstattung)" if candidate.source == "refund" else ""
    return Entry(
        author="Pretix",
        kind=candidate.kind,
        budget_id=budget,
        amount=candidate.amount,
        on=candidate.on,
        text=f"{link.name or link.slug} – {candidate.code}{suffix}",
        reference=candidate.code,
        event=(link.event_id, actor),
    )


async def _book_one(
    session: AsyncSession,
    link: PretixEventLink,
    candidate: Candidate,
    actor: uuid.UUID | None,
    budget: uuid.UUID,
) -> Outcome:
    result = (
        await book(session, _entry(link, candidate, actor, budget))
        if actor is not None
        else NO_ACTOR
    )
    await _record(session, link.slug, candidate, result)
    if isinstance(result, uuid.UUID):
        return Outcome(booked=1)
    return Outcome(failures=(Failure("pretix", candidate.source, candidate.key, result),))


async def _book(
    session: AsyncSession, link: PretixEventLink, wanted: Sequence[Candidate]
) -> Outcome:
    budget = link.income_budget_id
    if budget is None:
        return Outcome()
    done = await _done(session, link.slug)
    open_ones = [item for item in wanted if (item.source, item.key) not in done]
    if not open_ones:
        return Outcome()
    actor = await link_actor(session, link)
    return joined([await _book_one(session, link, item, actor, budget) for item in open_ones])


async def sync_link(
    session: AsyncSession,
    client: PretixClient,
    row: PretixSettings,
    link: PretixEventLink,
    now: datetime,
) -> Outcome:
    """Read the orders of one linked pretix event; store its sales and book its orders."""
    show = part_on(row, "sales")
    income = part_on(row, "income") and link.income_budget_id is not None
    if not show and not income:
        return Outcome()
    try:
        orders = await client.orders(link.slug)
        sales = (
            sales_of(await client.products(link.slug), await client.quotas(link.slug), orders)
            if show
            else None
        )
    except PretixError as exc:
        return Outcome(failures=(Failure("pretix", "read", link.slug, exc.code),))
    if sales is not None:
        await session.execute(
            update(PretixEventLink)
            .where(PretixEventLink.id == link.id)
            .values(sales=sales, sales_ok_at=now)
        )
    return await _book(session, link, candidates(orders)) if income else Outcome()


async def sync_links(
    session: AsyncSession,
    client: PretixClient,
    row: PretixSettings,
    links: Sequence[PretixEventLink],
    now: datetime,
) -> Outcome:
    """Run `sync_link` for each link, one after the other."""
    return joined([await sync_link(session, client, row, link, now) for link in links])


async def failed_bookings(session: AsyncSession) -> Sequence[PretixBooking]:
    """Return the bookings of orders that failed, the newest first (003086)."""
    return (
        await session.scalars(
            select(PretixBooking)
            .where(PretixBooking.state == "failed")
            .order_by(PretixBooking.updated_at.desc())
            .limit(200)
        )
    ).all()
