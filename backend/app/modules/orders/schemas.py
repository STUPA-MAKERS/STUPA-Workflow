"""API models of the Bestellungen."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from app.modules.budget.tree_schemas import InvoiceStatus
from app.modules.orders.rules import OrderKind, OrderStatus
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

#: An amount in euro: from 0, with at most two decimal places.
Amount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Note = Annotated[str, StringConstraints(max_length=2000)]
PositionId = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class OrderCreate(FrozenStrictCamelModel, frozen=True):
    """The body of a new Bestellung."""

    title: Title
    kind: OrderKind = "order"
    status: OrderStatus = "planned"
    supplier: Short | None = None
    url: str | None = None
    order_number: Annotated[str, StringConstraints(max_length=100)] | None = Field(
        default=None, alias="orderNumber"
    )
    position_ids: tuple[PositionId, ...] = Field(default=(), alias="positionIds", max_length=200)
    planned_amount: Amount | None = Field(default=None, alias="plannedAmount")
    actual_amount: Amount | None = Field(default=None, alias="actualAmount")
    ordered_on: date | None = Field(default=None, alias="orderedOn")
    delivered_on: date | None = Field(default=None, alias="deliveredOn")
    buyer_id: UUID | None = Field(default=None, alias="buyerId")
    buyer_name: Short | None = Field(default=None, alias="buyerName")
    note: Note | None = None


class OrderUpdate(FrozenStrictCamelModel, frozen=True):
    """The body of a change. A field that the body leaves out stays as it is.

    Attributes:
        version: The version that the person read.
    """

    version: int
    title: Title | None = None
    kind: OrderKind | None = None
    supplier: Short | None = None
    url: str | None = None
    order_number: Annotated[str, StringConstraints(max_length=100)] | None = Field(
        default=None, alias="orderNumber"
    )
    position_ids: tuple[PositionId, ...] | None = Field(
        default=None, alias="positionIds", max_length=200
    )
    planned_amount: Amount | None = Field(default=None, alias="plannedAmount")
    actual_amount: Amount | None = Field(default=None, alias="actualAmount")
    ordered_on: date | None = Field(default=None, alias="orderedOn")
    delivered_on: date | None = Field(default=None, alias="deliveredOn")
    buyer_id: UUID | None = Field(default=None, alias="buyerId")
    buyer_name: Short | None = Field(default=None, alias="buyerName")
    note: Note | None = None


class OrderStatusIn(FrozenStrictCamelModel, frozen=True):
    """The body of a status change."""

    status: OrderStatus
    version: int


class OrderInvoiceIn(FrozenStrictCamelModel, frozen=True):
    """The body that sets or removes the invoice of a Bestellung.

    Attributes:
        invoice_id: The invoice, or null to remove the reference.
        version: The version that the person read.
    """

    invoice_id: UUID | None = Field(alias="invoiceId")
    version: int


class OrderOut(FrozenCamelModel, frozen=True):
    """One Bestellung, as a person who reads the Antrag as a member sees it.

    Attributes:
        application_title: The title of the Antrag.
        buyer_label: The name of the account of the buyer, else the typed name.
        invoice_number: The number of the invoice of the Bestellung.
        invoice_status: The status of that invoice, read at each read
            (F/finance/orders/002880).
        booked_amount: The sum of the bookings that name the Bestellung, read at each
            read; 0 without a booking.
    """

    id: UUID
    number: str
    application_id: UUID | None = Field(default=None, alias="applicationId")
    application_title: str | None = Field(default=None, alias="applicationTitle")
    title: str
    kind: OrderKind
    status: OrderStatus
    supplier: str | None = None
    url: str | None = None
    order_number: str | None = Field(default=None, alias="orderNumber")
    position_ids: tuple[str, ...] = Field(default=(), alias="positionIds")
    planned_amount: Decimal | None = Field(default=None, alias="plannedAmount")
    actual_amount: Decimal | None = Field(default=None, alias="actualAmount")
    ordered_on: date | None = Field(default=None, alias="orderedOn")
    delivered_on: date | None = Field(default=None, alias="deliveredOn")
    buyer_id: UUID | None = Field(default=None, alias="buyerId")
    buyer_name: str | None = Field(default=None, alias="buyerName")
    buyer_label: str | None = Field(default=None, alias="buyerLabel")
    note: str | None = None
    invoice_id: UUID | None = Field(default=None, alias="invoiceId")
    invoice_number: str | None = Field(default=None, alias="invoiceNumber")
    invoice_status: InvoiceStatus | None = Field(default=None, alias="invoiceStatus")
    booked_amount: Decimal = Field(default=Decimal(0), alias="bookedAmount")
    version: int
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class OrderApplicantOut(FrozenCamelModel, frozen=True):
    """One Bestellung, as the applicant sees it: no price, no link and no note."""

    id: UUID
    number: str
    title: str
    kind: OrderKind
    status: OrderStatus
    ordered_on: date | None = Field(default=None, alias="orderedOn")
    delivered_on: date | None = Field(default=None, alias="deliveredOn")


class OrdersOut(FrozenCamelModel, frozen=True):
    """The Bestellungen of one Antrag.

    Attributes:
        total: The sum of the prices of the Bestellungen that are not cancelled. Null in
            the applicant view.
        approved_amount: The approved amount of the Antrag. Null in the applicant view.
        over_by: By how much the sum is above the approved amount, else null.
        can_manage: The reader holds ``order.manage``.
        can_create: The reader can create a Bestellung now: ``can_manage``, and the Antrag
            is approved and of a type with money.
    """

    items: tuple[OrderOut | OrderApplicantOut, ...]
    total: Decimal | None = None
    approved_amount: Decimal | None = Field(default=None, alias="approvedAmount")
    over_by: Decimal | None = Field(default=None, alias="overBy")
    can_manage: bool = Field(default=False, alias="canManage")
    can_create: bool = Field(default=False, alias="canCreate")


class InvoiceOrderOut(FrozenCamelModel, frozen=True):
    """One Bestellung in the detail of its invoice (F/finance/orders/002877).

    Attributes:
        accessible: The reader reads the Antrag of the Bestellung. Else the row holds
            no other value, and the page shows "Bestellung (kein Zugriff)".
    """

    accessible: bool
    id: UUID | None = None
    number: str | None = None
    title: str | None = None
    application_id: UUID | None = Field(default=None, alias="applicationId")
    application_title: str | None = Field(default=None, alias="applicationTitle")
    actual_amount: Decimal | None = Field(default=None, alias="actualAmount")


class InvoiceOrdersOut(FrozenCamelModel, frozen=True):
    """The Bestellungen that name one invoice.

    Attributes:
        total: The sum of the real prices of all these Bestellungen.
    """

    items: tuple[InvoiceOrderOut, ...]
    total: Decimal


class OrderBookingOut(FrozenCamelModel, frozen=True):
    """One booking that names a Bestellung (F/finance/orders/002889)."""

    id: UUID
    description: str | None = None
    amount: Decimal


class PendingApplicationOut(FrozenCamelModel, frozen=True):
    """One approved Antrag without a Bestellung (F/finance/orders/002934).

    Attributes:
        approved_amount: The approved amount of the Antrag, else null.
        gremium_name: The name of the Gremium of the Antrag, else null.
    """

    id: UUID
    title: str | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    approved_amount: Decimal | None = Field(default=None, alias="approvedAmount")
