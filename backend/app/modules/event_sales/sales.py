"""The section `Verkauf` of an Event: the pretix sales and the Mollie money.

Each person who reads the Event reads the sums (§F/integrations/pretix/003084,
§F/integrations/mollie/003096); the section holds only sums and numbers (003088, 003098).
A part shows only while its feature and its connection are on: the pretix sales need the
part `Verkaufszahlen zeigen` (003082), the Mollie money a payment of the Event (003095).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget
from app.modules.event_sales.mollie_sync import PAID_OUT, REFUNDED
from app.modules.event_sales.schemas import (
    EventSalesOut,
    MollieMoneyOut,
    PretixSalesOut,
    ProductSalesOut,
    QuotaOut,
    SettlementShareOut,
)
from app.modules.mollie.models import MollieMove, MolliePayment, MollieSettings, MollieSettlement
from app.modules.pretix.connection import connected, part_on
from app.modules.pretix.models import PretixEventLink, PretixSettings
from app.modules.pretix.schemas import LinkOut

#: The permission of the link to a pretix event (§F/integrations/pretix/003091).
PRETIX_USE = "pretix.use"
#: The permission of the field `Einnahmen-Kostenstelle` (003086).
BUDGET_BOOK = "budget.book"


def _number(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _decimal(value: object) -> Decimal:
    return Decimal(value) if isinstance(value, str) else Decimal(0)


def pretix_sales(link: PretixEventLink) -> PretixSalesOut | None:
    """Build the pretix part from the stored sales, else None without a read."""
    raw = link.sales
    if not raw:
        return None
    products = raw.get("products")
    quotas = raw.get("quotas")
    return PretixSalesOut(
        products=tuple(
            ProductSalesOut(
                name=str(row.get("name", "")),
                paid=_number(row.get("paid")),
                pending=_number(row.get("pending")),
                cancelled=_number(row.get("cancelled")),
            )
            for row in (products if isinstance(products, list) else [])
            if isinstance(row, dict)
        ),
        paid_sum=_decimal(raw.get("paidSum")),
        refund_sum=_decimal(raw.get("refundSum")),
        quotas=tuple(
            QuotaOut(
                name=str(row.get("name", "")),
                available=avail if isinstance(avail := row.get("available"), int) else None,
            )
            for row in (quotas if isinstance(quotas, list) else [])
            if isinstance(row, dict)
        ),
        read_at=link.sales_ok_at,
    )


def _sum(values: Iterable[Decimal]) -> Decimal:
    return sum(values, Decimal(0))


@dataclass(frozen=True, slots=True)
class _Money:
    payments: Sequence[MolliePayment]
    moves: Sequence[MollieMove]
    settlements: Sequence[MollieSettlement]


def _counted(move: MollieMove) -> bool:
    return move.kind == "chargeback" or move.status == REFUNDED


def _share(money: _Money, settlement: MollieSettlement) -> Decimal:
    """The net money of the Event in one settlement: payments less fees and moves."""
    paid = _sum(p.amount - (p.fee or 0) for p in money.payments if p.settlement_id == settlement.id)
    back = _sum(m.amount for m in money.moves if m.settlement_id == settlement.id and _counted(m))
    return paid - back


def mollie_money(money: _Money, read_at: datetime | None) -> MollieMoneyOut | None:
    """Build the Mollie part of the payments of one Event, else None without a payment."""
    if not money.payments:
        return None
    shares = tuple(
        SettlementShareOut(
            reference=item.reference, settled_at=item.settled_at, amount=_share(money, item)
        )
        for item in money.settlements
        if item.status == PAID_OUT
    )
    return MollieMoneyOut(
        paid=_sum(p.amount for p in money.payments),
        refunds=_sum(m.amount for m in money.moves if m.kind == "refund" and _counted(m)),
        chargebacks=_sum(m.amount for m in money.moves if m.kind == "chargeback"),
        fees=_sum(p.fee or Decimal(0) for p in money.payments),
        paid_out=_sum(share.amount for share in shares),
        settlements=shares,
        read_at=read_at,
    )


async def event_money(session: AsyncSession, organizer: str, slug: str) -> _Money:
    """Read the paid payments of a pretix event, their moves and their settlements."""
    payments = (
        await session.scalars(
            select(MolliePayment).where(
                MolliePayment.organizer == organizer,
                MolliePayment.event_slug == slug,
                MolliePayment.paid_at.is_not(None),
            )
        )
    ).all()
    ids = tuple(item.id for item in payments)
    moves = (
        (await session.scalars(select(MollieMove).where(MollieMove.payment_id.in_(ids)))).all()
        if ids
        else ()
    )
    settlement_ids = frozenset(
        value
        for value in (*(p.settlement_id for p in payments), *(m.settlement_id for m in moves))
        if value is not None
    )
    settlements = (
        (
            await session.scalars(
                select(MollieSettlement)
                .where(MollieSettlement.id.in_(settlement_ids))
                .order_by(MollieSettlement.settled_at)
            )
        ).all()
        if settlement_ids
        else ()
    )
    return _Money(payments=payments, moves=moves, settlements=settlements)


async def link_out(session: AsyncSession, link: PretixEventLink) -> LinkOut:
    """Return the link with the name of its cost centre."""
    name = (
        await session.scalar(select(Budget.name).where(Budget.id == link.income_budget_id))
        if link.income_budget_id is not None
        else None
    )
    return LinkOut(
        slug=link.slug,
        name=link.name,
        date_from=link.date_from,
        income_budget_id=link.income_budget_id,
        income_budget_name=name,
    )


@dataclass(frozen=True, slots=True)
class SalesContext:
    """What the section of one Event needs: the settings and which features are on."""

    pretix: PretixSettings
    mollie: MollieSettings
    pretix_on: bool
    mollie_on: bool


async def event_sales(
    session: AsyncSession,
    event_id: uuid.UUID,
    principal: Principal,
    context: SalesContext,
) -> EventSalesOut:
    """Build the section `Verkauf` of an Event that the principal reads."""
    pretix_connected = context.pretix_on and connected(context.pretix)
    link = (
        await session.scalar(select(PretixEventLink).where(PretixEventLink.event_id == event_id))
        if pretix_connected
        else None
    )
    organizer = context.pretix.organizer
    money = (
        mollie_money(await event_money(session, organizer, link.slug), context.mollie.read_ok_at)
        if link is not None and organizer and context.mollie_on and context.mollie.token
        else None
    )
    return EventSalesOut(
        connected=pretix_connected,
        link=await link_out(session, link) if link is not None else None,
        pretix=(
            pretix_sales(link) if link is not None and part_on(context.pretix, "sales") else None
        ),
        mollie=money,
        linkable=pretix_connected and principal.has(PRETIX_USE),
        income_editable=link is not None and principal.has(BUDGET_BOOK),
        income_on=pretix_connected and part_on(context.pretix, "income"),
        refreshable=link is not None or money is not None,
    )
