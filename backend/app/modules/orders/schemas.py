"""API models of the Bestellungen."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

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


class OrderOut(FrozenCamelModel, frozen=True):
    """One Bestellung, as a person who reads the Antrag as a member sees it.

    Attributes:
        buyer_label: The name of the account of the buyer, else the typed name.
    """

    id: UUID
    number: str
    application_id: UUID = Field(alias="applicationId")
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
