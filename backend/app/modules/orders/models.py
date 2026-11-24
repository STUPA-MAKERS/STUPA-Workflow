"""Tables of the Bestellungen: ``purchase_order`` and its positions.

The table is ``purchase_order``, because ``order`` is a reserved word of SQL.

A Bestellung belongs to exactly one Antrag and goes with it (F/finance/orders/002850). It
holds no figure of the Haushalt: the Antrag and its bookings set those
(F/finance/orders/002857). ``invoice_id`` names at most one invoice, and the delete of the
invoice clears it (F/finance/orders/002873).

``purchase_order_position`` holds the positions of the Kostenaufstellung that a Bestellung
covers, by the ``id`` of the position in the data of the Antrag (F/finance/orders/002860).

The timeline events of a Bestellung are rows of ``purchase_order_event``. That table belongs to
the module ``applications`` (`ApplicationOrderEvent`), because the timeline of the Antrag reads
it and a module imports only from its own layer and from lower layers.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin
from app.modules.orders.numbers import draw_number

#: The kinds of a Bestellung: an order of the organization or an Auslage of a person.
ORDER_KINDS: tuple[str, ...] = ("order", "outlay")
#: The statuses of a Bestellung, in the order of the usual way.
ORDER_STATUSES: tuple[str, ...] = ("planned", "ordered", "delivered", "cancelled")


def _in(values: tuple[str, ...]) -> str:
    """Render the values as the list of an SQL ``IN``."""
    return ", ".join(f"'{value}'" for value in values)


class PurchaseOrder(UUIDPkMixin, TimestampMixin, Base):
    """One Bestellung of an Antrag.

    Attributes:
        number: The eight random characters of the number, unique on the platform.
        application_id: The Antrag; it never changes.
        kind: ``order`` or ``outlay``.
        status: ``planned``, ``ordered``, ``delivered`` or ``cancelled``.
        title: The Bezeichnung.
        supplier: The Händler.
        url: The link to the shop or the article, http or https only.
        order_number: The Bestellnummer of the Händler.
        planned_amount: The planned price in euro.
        actual_amount: The real gross price in euro.
        buyer_id: The account of the person who bought, else NULL.
        buyer_name: The typed name of the person who bought, else NULL.
        invoice_id: The invoice of the purchase, else NULL.
        version: Raised by each write; a change names the version it read.
        created_by: The ``sub`` of the person who created the row.
    """

    __tablename__ = "purchase_order"

    number: Mapped[str] = mapped_column(Text, default=draw_number, unique=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text, server_default="order")
    status: Mapped[str] = mapped_column(Text, server_default="planned")
    title: Mapped[str] = mapped_column(Text)
    supplier: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ordered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    buyer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )
    buyer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoice.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(ORDER_KINDS)})", name="kind"),
        CheckConstraint(f"status IN ({_in(ORDER_STATUSES)})", name="status"),
        CheckConstraint("planned_amount IS NULL OR planned_amount >= 0", name="planned_amount"),
        CheckConstraint("actual_amount IS NULL OR actual_amount >= 0", name="actual_amount"),
        CheckConstraint(
            "kind <> 'outlay' OR buyer_id IS NOT NULL OR buyer_name IS NOT NULL", name="buyer"
        ),
        Index("ix_purchase_order_application_id", "application_id"),
        Index("ix_purchase_order_invoice_id", "invoice_id"),
    )


class PurchaseOrderPosition(Base):
    """One position of the Kostenaufstellung that a Bestellung covers."""

    __tablename__ = "purchase_order_position"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order.id", ondelete="CASCADE"), primary_key=True
    )
    position_id: Mapped[str] = mapped_column(Text, primary_key=True)
