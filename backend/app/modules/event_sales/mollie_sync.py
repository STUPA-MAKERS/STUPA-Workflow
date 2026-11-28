"""The read of the Mollie money data and its bookings.

`read_mollie` reads the new payments, refunds, chargebacks, settlements and the fee of
each payment (§F/integrations/mollie/003094). Mollie lists the newest first, so a read
stops at the first page whose rows the platform already holds in a final state. A failed
read keeps the stored data and the time of the last read that worked.

`book_mollie` books, while the switch `Einnahmen buchen` is on (003082): each paid out
settlement with its fees on the field `Gebühren-Kostenstelle`, one sub-booking per Event
that has a payment in it plus one for the rest (003097), and each paid payment without an
Event, its refunds and its chargebacks on the field `Kostenstelle für Zahlungen ohne
Veranstaltung` (003103). A payment belongs to an Event only by its pretix metadata (003095).

No function here commits. The worker and the router own the transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.event_sales.booking import NO_ACTOR, Entry, Part, book
from app.modules.event_sales.outcome import Failure, Outcome, joined
from app.modules.event_sales.pretix_sync import link_actor
from app.modules.mollie.client import (
    Fee,
    Known,
    MollieClient,
    MollieError,
    Move,
    Payment,
    Settlement,
)
from app.modules.mollie.models import (
    MollieBooking,
    MollieMove,
    MolliePayment,
    MollieSettings,
    MollieSettlement,
)
from app.modules.pretix.models import PretixEventLink, PretixSettings

#: The payment statuses that never change again.
FINAL_PAYMENT = ("failed", "canceled", "expired")
#: The status of a refund that Mollie finished.
REFUNDED = "refunded"
#: The status of a settlement that Mollie paid out.
PAID_OUT = "paidout"

type Row = Mapping[str, object]


def _ids(rows: Iterable[Row]) -> frozenset[str]:
    return frozenset(value for row in rows if isinstance(value := row.get("id"), str))


async def _final_payments(session: AsyncSession) -> frozenset[str]:
    rows = await session.scalars(
        select(MolliePayment.id).where(
            (MolliePayment.settlement_id.is_not(None)) | MolliePayment.status.in_(FINAL_PAYMENT)
        )
    )
    return frozenset(rows.all())


async def _final_moves(session: AsyncSession) -> frozenset[str]:
    rows = await session.scalars(select(MollieMove.id).where(MollieMove.settlement_id.is_not(None)))
    return frozenset(rows.all())


async def _final_settlements(session: AsyncSession) -> frozenset[str]:
    rows = await session.scalars(
        select(MollieSettlement.id).where(MollieSettlement.status == PAID_OUT)
    )
    return frozenset(rows.all())


async def _fee_known(session: AsyncSession) -> frozenset[str]:
    rows = await session.scalars(select(MolliePayment.id).where(MolliePayment.fee.is_not(None)))
    return frozenset(rows.all())


def _transactions_known(known: frozenset[str]) -> Known:
    def check(rows: tuple[Row, ...]) -> bool:
        payment_ids = [
            context.get("paymentId")
            for row in rows
            if row.get("type") == "payment" and isinstance(context := row.get("context"), dict)
        ]
        return all(isinstance(pid, str) and pid in known for pid in payment_ids)

    return check


async def _store_payments(session: AsyncSession, payments: Sequence[Payment]) -> None:
    for payment in payments:
        values = {
            "amount": payment.amount,
            "status": payment.status,
            "created": payment.created_at,
            "paid_at": payment.paid_at,
            "settlement_id": payment.settlement_id,
            "organizer": payment.organizer,
            "event_slug": payment.event,
        }
        await session.execute(
            pg_insert(MolliePayment)
            .values(id=payment.id, **values)
            .on_conflict_do_update(index_elements=[MolliePayment.id], set_=values)
        )


async def _store_moves(session: AsyncSession, moves: Sequence[Move]) -> None:
    for move in moves:
        values = {
            "kind": move.kind,
            "payment_id": move.payment_id,
            "amount": move.amount,
            "status": move.status,
            "at": move.at,
            "settlement_id": move.settlement_id,
        }
        await session.execute(
            pg_insert(MollieMove)
            .values(id=move.id, **values)
            .on_conflict_do_update(index_elements=[MollieMove.id], set_=values)
        )


async def _store_settlements(session: AsyncSession, settlements: Sequence[Settlement]) -> None:
    for item in settlements:
        values = {
            "reference": item.reference,
            "status": item.status,
            "settled_at": item.settled_at,
            "amount": item.amount,
            "fees": item.fees,
        }
        await session.execute(
            pg_insert(MollieSettlement)
            .values(id=item.id, **values)
            .on_conflict_do_update(index_elements=[MollieSettlement.id], set_=values)
        )


async def _store_fees(session: AsyncSession, fees: Sequence[Fee]) -> None:
    for fee in fees:
        await session.execute(
            update(MolliePayment).where(MolliePayment.id == fee.payment_id).values(fee=fee.fee)
        )


async def _mark_read(session: AsyncSession, **values: object) -> None:
    """Keep the moment or the cause of the newest read on the connection (003094)."""
    await session.execute(update(MollieSettings).where(MollieSettings.id == 1).values(**values))


async def read_mollie(session: AsyncSession, client: MollieClient, now: datetime) -> Outcome:
    """Read the new money data of Mollie and store it; keep the old data on a failure."""
    final_payments = await _final_payments(session)
    final_moves = await _final_moves(session)
    final_settlements = await _final_settlements(session)
    fee_known = await _fee_known(session)
    try:
        payments = await client.payments(lambda rows: _ids(rows) <= final_payments)
        refunds = await client.refunds(lambda rows: _ids(rows) <= final_moves)
        chargebacks = await client.chargebacks(lambda rows: _ids(rows) <= final_moves)
        settlements = await client.settlements(lambda rows: _ids(rows) <= final_settlements)
        fees = await client.fees(_transactions_known(fee_known))
    except MollieError as exc:
        await _mark_read(session, read_error=exc.code)
        return Outcome(failures=(Failure("mollie", "read", "mollie", exc.code),))
    await _store_payments(session, payments)
    await _store_moves(session, refunds + chargebacks)
    await _store_settlements(session, settlements)
    await session.flush()
    await _store_fees(session, fees)
    await _mark_read(session, read_ok_at=now, read_error=None)
    return Outcome()


@dataclass(frozen=True, slots=True)
class Links:
    """The pretix events of the connection that an Event links, by slug."""

    organizer: str | None
    by_slug: Mapping[str, PretixEventLink]

    def of(self, organizer: str | None, slug: str | None) -> PretixEventLink | None:
        """Return the link of a payment by its metadata, else None (003095)."""
        if self.organizer is None or organizer != self.organizer or slug is None:
            return None
        return self.by_slug.get(slug)


async def links_of(session: AsyncSession, pretix: PretixSettings) -> Links:
    """Read the links of the Events to the pretix events of the connection."""
    rows = (await session.scalars(select(PretixEventLink))).all()
    return Links(organizer=pretix.organizer, by_slug={row.slug: row for row in rows})


async def _booked(session: AsyncSession, source: str) -> frozenset[str]:
    rows = await session.scalars(
        select(MollieBooking.source_id).where(
            MollieBooking.source == source, MollieBooking.state == "booked"
        )
    )
    return frozenset(rows.all())


async def _record(
    session: AsyncSession, source: str, source_id: str, result: uuid.UUID | str
) -> Outcome:
    booked = isinstance(result, uuid.UUID)
    values = {
        "state": "booked" if booked else "failed",
        "expense_id": result if booked else None,
        "error": None if booked else result,
    }
    await session.execute(
        pg_insert(MollieBooking)
        .values(id=uuid.uuid4(), source=source, source_id=source_id, **values)
        .on_conflict_do_update(constraint="uq_mollie_booking_source", set_=values)
    )
    if isinstance(result, uuid.UUID):
        return Outcome(booked=1)
    return Outcome(failures=(Failure("mollie", source, source_id, result),))


async def _book_unassigned(session: AsyncSession, budget: uuid.UUID, links: Links) -> Outcome:
    payments = (
        await session.scalars(select(MolliePayment).where(MolliePayment.paid_at.is_not(None)))
    ).all()
    loose = {
        item.id: item for item in payments if links.of(item.organizer, item.event_slug) is None
    }
    done_payments = await _booked(session, "payment")
    paid = [
        await _record(
            session,
            "payment",
            item.id,
            await book(
                session,
                Entry(
                    author="Mollie",
                    kind="income",
                    budget_id=budget,
                    amount=item.amount,
                    on=item.paid_at.date() if item.paid_at else None,
                    text=f"Mollie {item.id}",
                    reference=item.id,
                ),
            ),
        )
        for item in loose.values()
        if item.id not in done_payments and item.amount > 0
    ]
    moves = (
        await session.scalars(select(MollieMove).where(MollieMove.payment_id.in_(tuple(loose))))
    ).all()
    done_moves = {
        "refund": await _booked(session, "refund"),
        "chargeback": await _booked(session, "chargeback"),
    }
    back = [
        await _record(
            session,
            move.kind,
            move.id,
            await book(
                session,
                Entry(
                    author="Mollie",
                    kind="expense",
                    budget_id=budget,
                    amount=move.amount,
                    on=move.at.date() if move.at else None,
                    text=f"Mollie {move.payment_id} – {move.id}",
                    reference=move.id,
                ),
            ),
        )
        for move in moves
        if move.id not in done_moves[move.kind]
        and move.amount > 0
        and (move.kind == "chargeback" or move.status == REFUNDED)
    ]
    return joined(paid + back)


async def _parts(
    session: AsyncSession, settlement: MollieSettlement, links: Links
) -> tuple[Part, ...] | str:
    """The sub-bookings of a settlement: the fees of each Event and the rest (003097)."""
    payments = (
        await session.scalars(
            select(MolliePayment).where(MolliePayment.settlement_id == settlement.id)
        )
    ).all()
    pairs = [
        (link, item.fee)
        for item in payments
        if (link := links.of(item.organizer, item.event_slug)) is not None and item.fee
    ]
    event_links = {link.event_id: link for link, _fee in pairs}
    shares = {
        event_id: (
            link,
            sum((fee for other, fee in pairs if other.event_id == event_id), Decimal(0)),
        )
        for event_id, link in event_links.items()
    }
    if not shares:
        return ()
    actors = {
        event_id: await link_actor(session, link) for event_id, (link, _fee) in shares.items()
    }
    if any(actor is None for actor in actors.values()):
        return NO_ACTOR
    rest = settlement.fees - sum((fee for _link, fee in shares.values()), Decimal(0))
    events = tuple(
        Part(
            amount=fee,
            text=f"Mollie {settlement.reference} – {link.name or link.slug}",
            event=(event_id, actor),
        )
        for event_id, (link, fee) in shares.items()
        if (actor := actors[event_id]) is not None
    )
    other = (
        (Part(amount=rest, text=f"Mollie {settlement.reference}", event=None),) if rest > 0 else ()
    )
    return events + other


async def _book_settlement(
    session: AsyncSession, settlement: MollieSettlement, budget: uuid.UUID, links: Links
) -> Outcome:
    parts = await _parts(session, settlement, links)
    result = (
        parts
        if isinstance(parts, str)
        else await book(
            session,
            Entry(
                author="Mollie",
                kind="expense",
                budget_id=budget,
                amount=settlement.fees,
                on=settlement.settled_at.date() if settlement.settled_at else None,
                text=f"Mollie {settlement.reference}",
                reference=settlement.reference,
                parts=parts,
            ),
        )
    )
    return await _record(session, "settlement", settlement.id, result)


async def _book_fees(session: AsyncSession, budget: uuid.UUID, links: Links) -> Outcome:
    done = await _booked(session, "settlement")
    settlements = (
        await session.scalars(
            select(MollieSettlement).where(
                MollieSettlement.status == PAID_OUT, MollieSettlement.fees > 0
            )
        )
    ).all()
    return joined(
        [
            await _book_settlement(session, item, budget, links)
            for item in settlements
            if item.id not in done
        ]
    )


async def book_mollie(
    session: AsyncSession, row: MollieSettings, pretix: PretixSettings
) -> Outcome:
    """Book the settlements and the payments without an Event (003097, 003103)."""
    if not pretix.book_income:
        return Outcome()
    links = await links_of(session, pretix)
    fees = (
        await _book_fees(session, row.fee_budget_id, links)
        if row.fee_budget_id is not None
        else Outcome()
    )
    loose = (
        await _book_unassigned(session, row.unassigned_budget_id, links)
        if row.unassigned_budget_id is not None
        else Outcome()
    )
    return fees + loose


async def failed_bookings(session: AsyncSession) -> Sequence[MollieBooking]:
    """Return the Mollie bookings that failed, the newest first (003097)."""
    return (
        await session.scalars(
            select(MollieBooking)
            .where(MollieBooking.state == "failed")
            .order_by(MollieBooking.updated_at.desc())
            .limit(200)
        )
    ).all()
