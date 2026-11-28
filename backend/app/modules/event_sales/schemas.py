"""API models of the sales of an Event and of the run `Daten abrufen`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.modules.pretix.schemas import FailedBookingOut, LinkOut
from app.shared.schemas import FrozenCamelModel


class ProductSalesOut(FrozenCamelModel, frozen=True):
    """The positions of one product by the state of their orders (003084)."""

    name: str
    paid: int
    pending: int
    cancelled: int


class QuotaOut(FrozenCamelModel, frozen=True):
    """The free places of one quota; None for a quota without a limit."""

    name: str
    available: int | None = None


class PretixSalesOut(FrozenCamelModel, frozen=True):
    """The sales of the linked pretix event and the time of the last read that worked."""

    products: tuple[ProductSalesOut, ...]
    paid_sum: Decimal = Field(serialization_alias="paidSum")
    refund_sum: Decimal = Field(serialization_alias="refundSum")
    quotas: tuple[QuotaOut, ...]
    read_at: datetime | None = Field(default=None, serialization_alias="readAt")


class SettlementShareOut(FrozenCamelModel, frozen=True):
    """The part of one settlement that belongs to the Event (003096)."""

    reference: str
    settled_at: datetime | None = Field(default=None, serialization_alias="settledAt")
    amount: Decimal


class MollieMoneyOut(FrozenCamelModel, frozen=True):
    """The money of the payments of the Event in Mollie (003096)."""

    paid: Decimal
    refunds: Decimal
    chargebacks: Decimal
    fees: Decimal
    paid_out: Decimal = Field(serialization_alias="paidOut")
    settlements: tuple[SettlementShareOut, ...]
    read_at: datetime | None = Field(default=None, serialization_alias="readAt")


class EventSalesOut(FrozenCamelModel, frozen=True):
    """The section `Verkauf` of an Event and what the reader may do with it.

    ``pretix`` and ``mollie`` are None while their part is off or holds no data.
    ``link`` is the linked pretix event while the connection is complete.
    ``linkable`` tells that the reader may set the link (003083, 003091),
    ``incomeEditable`` that the reader may set `Einnahmen-Kostenstelle` (003086),
    ``refreshable`` that the reader has the action `Aktualisieren` (003085).
    """

    connected: bool = False
    link: LinkOut | None = None
    pretix: PretixSalesOut | None = None
    mollie: MollieMoneyOut | None = None
    linkable: bool = False
    income_editable: bool = Field(default=False, serialization_alias="incomeEditable")
    income_on: bool = Field(default=False, serialization_alias="incomeOn")
    refreshable: bool = False


class SyncFailureOut(FrozenCamelModel, frozen=True):
    """One failure of a run with its cause."""

    integration: str
    source: str
    key: str
    cause: str


class SyncResultOut(FrozenCamelModel, frozen=True):
    """The result of a run: the number of new bookings and each failure (003104)."""

    booked: int
    failures: tuple[SyncFailureOut, ...]


class SyncStateOut(FrozenCamelModel, frozen=True):
    """Which integrations the action `Daten abrufen` reads now (003104)."""

    pretix: bool
    mollie: bool


class FailedBookingsOut(FrozenCamelModel, frozen=True):
    """The bookings that failed, for the admin page of an integration."""

    items: tuple[FailedBookingOut, ...]
