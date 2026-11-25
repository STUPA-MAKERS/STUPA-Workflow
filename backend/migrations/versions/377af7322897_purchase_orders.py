"""Bestellungen: the tables and the permission ``order.manage``.

The upgrade:

1. creates ``purchase_order``: one Bestellung of an Antrag, with the Bezeichnung, the
   Händler, the link, the prices, the status, the dates, the buyer and the invoice.
2. creates ``purchase_order_position``: the positions of the Kostenaufstellung that a
   Bestellung covers.
3. creates ``purchase_order_event``: the events of the Bestellungen in the timeline of
   the Antrag.
4. grants ``order.manage`` to the ``admin`` role.

The revision creates no Bestellung, because only a person creates one. All steps are
idempotent. A fresh database already gets the tables from the ``create_all`` baseline
(0001), because the models sit in ``app.models``.

Revision ID: 377af7322897
Revises: b7e3a91d4c58
Create Date: 2026-11-24 18:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "377af7322897"
down_revision: str | None = "b7e3a91d4c58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS purchase_order (
        number TEXT NOT NULL,
        application_id UUID,
        kind TEXT DEFAULT 'order' NOT NULL,
        status TEXT DEFAULT 'planned' NOT NULL,
        title TEXT NOT NULL,
        supplier TEXT,
        url TEXT,
        order_number TEXT,
        planned_amount NUMERIC(12, 2),
        actual_amount NUMERIC(12, 2),
        ordered_on DATE,
        delivered_on DATE,
        buyer_id UUID,
        buyer_name TEXT,
        note TEXT,
        invoice_id UUID,
        version INTEGER DEFAULT '1' NOT NULL,
        created_by TEXT,
        id UUID DEFAULT gen_random_uuid() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        CONSTRAINT pk_purchase_order PRIMARY KEY (id),
        CONSTRAINT ck_purchase_order_kind CHECK (kind IN ('order', 'outlay')),
        CONSTRAINT ck_purchase_order_status
            CHECK (status IN ('planned', 'ordered', 'delivered', 'cancelled')),
        CONSTRAINT ck_purchase_order_planned_amount
            CHECK (planned_amount IS NULL OR planned_amount >= 0),
        CONSTRAINT ck_purchase_order_actual_amount
            CHECK (actual_amount IS NULL OR actual_amount >= 0),
        CONSTRAINT uq_purchase_order_number UNIQUE (number),
        CONSTRAINT fk_purchase_order_application_id_application
            FOREIGN KEY(application_id)
            REFERENCES application (id) ON DELETE CASCADE,
        CONSTRAINT fk_purchase_order_buyer_id_principal
            FOREIGN KEY(buyer_id)
            REFERENCES principal (id) ON DELETE SET NULL,
        CONSTRAINT fk_purchase_order_invoice_id_invoice
            FOREIGN KEY(invoice_id)
            REFERENCES invoice (id) ON DELETE SET NULL
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_purchase_order_application_id "
        "ON purchase_order (application_id)"
    ),
    "CREATE INDEX IF NOT EXISTS ix_purchase_order_invoice_id ON purchase_order (invoice_id)",
    """
    CREATE TABLE IF NOT EXISTS purchase_order_position (
        order_id UUID NOT NULL,
        position_id TEXT NOT NULL,
        CONSTRAINT pk_purchase_order_position PRIMARY KEY (order_id, position_id),
        CONSTRAINT fk_purchase_order_position_order_id_purchase_order
            FOREIGN KEY(order_id)
            REFERENCES purchase_order (id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS purchase_order_event (
        application_id UUID NOT NULL,
        order_id UUID NOT NULL,
        actor TEXT,
        kind TEXT NOT NULL,
        payload JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        id UUID DEFAULT gen_random_uuid() NOT NULL,
        CONSTRAINT pk_purchase_order_event PRIMARY KEY (id),
        CONSTRAINT ck_purchase_order_event_kind CHECK (kind IN ('created', 'status', 'deleted')),
        CONSTRAINT fk_purchase_order_event_application_id_application
            FOREIGN KEY(application_id)
            REFERENCES application (id) ON DELETE CASCADE
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_purchase_order_event_application_id "
        "ON purchase_order_event (application_id)"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'order.manage' FROM role r WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'order.manage'",
    "DROP TABLE IF EXISTS purchase_order_event",
    "DROP TABLE IF EXISTS purchase_order_position",
    "DROP TABLE IF EXISTS purchase_order",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
