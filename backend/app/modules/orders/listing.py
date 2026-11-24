"""The page "Bestellungen": the Bestellungen of all Anträge and the Anträge without one.

Both lists hold only the Anträge that the caller reads as a member
(F/finance/orders/002883). The filters read the Kostenstelle, the Haushaltsjahr and the
Gremium of the Antrag, because a Bestellung has none of its own (F/finance/orders/002885).
The functions read only the flags of a state and of a type and never a key of the flow,
because the flow is the configuration of each installation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import Application
from app.modules.applications.service import ApplicationsService
from app.modules.applications.service.service_base import _title_of
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import BudgetExpense
from app.modules.flow.models import State
from app.modules.gremien.models import Gremium
from app.modules.orders.models import PurchaseOrder
from app.modules.orders.rules import OrderKind, Segment
from app.modules.orders.schemas import PendingApplicationOut
from app.shared.paging import Page
from app.shared.search import dialect_of, trigram_rank


@dataclass(frozen=True, slots=True)
class OrderFilter:
    """The filter of the page "Bestellungen" (F/finance/orders/002885).

    Attributes:
        segment: The segment, else every Bestellung.
        fiscal_year_id: The Haushaltsjahr of the Antrag.
        budget_id: The Kostenstelle of the Antrag; its subtree counts.
        gremium_id: The Gremium of the Antrag.
        kind: ``order`` or ``outlay``.
        buyer_id: The account of the buyer.
        q: The search in the number, the Bezeichnung, the Händler and the Bestellnummer.
    """

    segment: Segment | None = None
    fiscal_year_id: UUID | None = None
    budget_id: UUID | None = None
    gremium_id: UUID | None = None
    kind: OrderKind | None = None
    buyer_id: UUID | None = None
    q: str | None = None


def _booked() -> ColumnElement[Decimal]:
    """Build the sum of the bookings that name the Bestellung of the outer row."""
    return (
        select(func.coalesce(func.sum(BudgetExpense.amount), 0))
        .where(
            BudgetExpense.order_id == PurchaseOrder.id,
            BudgetExpense.parent_expense_id.is_(None),
        )
        .correlate(PurchaseOrder)
        .scalar_subquery()
    )


def segment_clause(segment: Segment) -> ColumnElement[bool]:
    """Build the rule of `rules.segment_of` as SQL."""
    cost = func.coalesce(PurchaseOrder.actual_amount, PurchaseOrder.planned_amount)
    booked = _booked()
    waits = or_(and_(cost.is_not(None), booked < cost), and_(cost.is_(None), booked == 0))
    match segment:
        case "open":
            return PurchaseOrder.status.in_(("planned", "ordered"))
        case "delivered":
            return and_(PurchaseOrder.status == "delivered", waits)
        case "done":
            return or_(
                PurchaseOrder.status == "cancelled",
                and_(PurchaseOrder.status == "delivered", ~waits),
            )


@dataclass(frozen=True, slots=True)
class OrderListing:
    """The two lists of the page "Bestellungen", bound to an ``AsyncSession``."""

    session: AsyncSession

    async def _application_filters(
        self, principal: Principal, wanted: OrderFilter
    ) -> list[ColumnElement[bool]]:
        """Build the clauses on the Antrag: the read scope and the filters."""
        apps = ApplicationsService(self.session)
        scope = await apps.member_scope_for(principal)
        optional = (
            scope,
            (
                Application.fiscal_year_id == wanted.fiscal_year_id
                if wanted.fiscal_year_id is not None
                else None
            ),
            (await apps.subtree_scope(wanted.budget_id) if wanted.budget_id is not None else None),
            Application.gremium_id == wanted.gremium_id if wanted.gremium_id is not None else None,
        )
        return [
            Application.email_confirmed_at.is_not(None),
            *(clause for clause in optional if clause is not None),
        ]

    def _search(self, q: str | None) -> tuple[ColumnElement[bool], ColumnElement[Any]] | None:
        """Build the search clause and its rank, or None without a query.

        A person types the number as the page shows it, so the ``B-`` goes before the
        search reads the stored characters.
        """
        text = (q or "").strip()
        if not text:
            return None
        return trigram_rank(
            text.removeprefix("B-").removeprefix("b-") or text,
            [
                PurchaseOrder.number,
                PurchaseOrder.title,
                PurchaseOrder.supplier,
                PurchaseOrder.order_number,
            ],
            dialect=dialect_of(self.session),
        )

    async def page(
        self, principal: Principal, wanted: OrderFilter, *, limit: int, offset: int
    ) -> tuple[list[PurchaseOrder], int]:
        """Return one page of the Bestellungen, the newest change first, and the total.

        An active search puts the best hit first.
        """
        search = self._search(wanted.q)
        optional = (
            segment_clause(wanted.segment) if wanted.segment is not None else None,
            PurchaseOrder.kind == wanted.kind if wanted.kind is not None else None,
            PurchaseOrder.buyer_id == wanted.buyer_id if wanted.buyer_id is not None else None,
            search[0] if search is not None else None,
        )
        filters = [
            *(await self._application_filters(principal, wanted)),
            *(clause for clause in optional if clause is not None),
        ]
        joined = select(PurchaseOrder).join(
            Application, Application.id == PurchaseOrder.application_id
        )
        total = await self.session.scalar(
            select(func.count()).select_from(joined.where(*filters).subquery())
        )
        newest = (PurchaseOrder.updated_at.desc(), PurchaseOrder.id)
        rows = await self.session.scalars(
            joined.where(*filters)
            .order_by(*((search[1].desc(), *newest) if search is not None else newest))
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total or 0

    async def pending(
        self,
        principal: Principal,
        wanted: OrderFilter,
        *,
        limit: int,
        offset: int,
        with_orders: bool = False,
    ) -> Page[PendingApplicationOut]:
        """Return the approved Anträge without a Bestellung (F/finance/orders/002934).

        An Antrag counts when its state has the flag approved, its type has money and no
        Bestellung of it has a status other than "Storniert". An archived Antrag is out
        of the work, so the list leaves it out. The newest Antrag stands first.

        ``with_orders`` keeps the Anträge that have a Bestellung too, because the form of
        a new Bestellung offers every Antrag that can take one (F/finance/orders/002937).
        """
        has_order = (
            select(PurchaseOrder.id)
            .where(
                PurchaseOrder.application_id == Application.id,
                PurchaseOrder.status != "cancelled",
            )
            .exists()
        )
        filters = [
            *(await self._application_filters(principal, wanted)),
            Application.archived_at.is_(None),
            ApplicationType.has_budget.is_(True),
            State.is_approved.is_(True),
            *(() if with_orders else (~has_order,)),
        ]
        joined = (
            select(
                Application.id,
                Application.data,
                Application.gremium_id,
                Gremium.name,
                Application.approved_amount,
            )
            .join(ApplicationType, ApplicationType.id == Application.type_id)
            .join(State, State.id == Application.current_state_id)
            .outerjoin(Gremium, Gremium.id == Application.gremium_id)
            .where(*filters)
        )
        total = await self.session.scalar(select(func.count()).select_from(joined.subquery()))
        rows = (
            await self.session.execute(
                joined.order_by(Application.created_at.desc(), Application.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return Page(
            items=[
                PendingApplicationOut(
                    id=application_id,
                    title=_title_of(data),
                    gremiumId=gremium_id,
                    gremiumName=gremium_name,
                    approvedAmount=approved,
                )
                for application_id, data, gremium_id, gremium_name, approved in rows
            ],
            total=total or 0,
            limit=limit,
            offset=offset,
        )
