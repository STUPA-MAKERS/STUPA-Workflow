"""pretix and mollie: the connections, the links of the Events, the money data, the bookings.

``pretix_settings`` and ``mollie_settings`` are the single rows of the two connections
(§F/integrations/pretix/003080, §F/integrations/mollie/003092). ``pretix_event_link`` links
an Event to one pretix event and keeps its sales (003083, 003084). ``mollie_payment``,
``mollie_move`` and ``mollie_settlement`` hold the money data of Mollie without a value of
the payer (003098). ``pretix_booking`` and ``mollie_booking`` keep one row per booked
source, so a run never books twice (003086, 003097, 003103).

Idempotent. A fresh database already gets the tables from the ``create_all`` baseline
(0001), because the models sit in ``app.models``. A migrated database gets them through
``CREATE TABLE IF NOT EXISTS``.

The revision also grants ``admin.pretix``, ``admin.mollie`` and ``pretix.use`` to the
``admin`` role. No other seeded role gets them (§F/integrations/pretix/003091).

Revision ID: 75d610e3b5f3
Revises: ffe68b6e919b
Create Date: 2026-11-28 06:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "75d610e3b5f3"
down_revision: str | None = "ffe68b6e919b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSIONS = "('admin.pretix'), ('admin.mollie'), ('pretix.use')"

_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS pretix_settings (
            id INTEGER NOT NULL,
            base_url TEXT,
            organizer TEXT,
            token TEXT,
            show_sales BOOLEAN DEFAULT 'false' NOT NULL,
            book_income BOOLEAN DEFAULT 'false' NOT NULL,
            CONSTRAINT pk_pretix_settings PRIMARY KEY (id),
            CONSTRAINT ck_pretix_settings_singleton CHECK (id = 1)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pretix_event_link (
            event_id UUID NOT NULL,
            slug TEXT NOT NULL,
            name TEXT DEFAULT '' NOT NULL,
            date_from DATE,
            income_budget_id UUID,
            sales JSONB,
            sales_ok_at TIMESTAMP WITH TIME ZONE,
            refreshed_at TIMESTAMP WITH TIME ZONE,
            created_by UUID,
            id UUID DEFAULT gen_random_uuid() NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_pretix_event_link PRIMARY KEY (id),
            CONSTRAINT uq_pretix_event_link_event_id UNIQUE (event_id),
            CONSTRAINT fk_pretix_event_link_event_id_event
                FOREIGN KEY(event_id) REFERENCES event (id) ON DELETE CASCADE,
            CONSTRAINT uq_pretix_event_link_slug UNIQUE (slug),
            CONSTRAINT fk_pretix_event_link_income_budget_id_budget
                FOREIGN KEY(income_budget_id) REFERENCES budget (id) ON DELETE SET NULL,
            CONSTRAINT fk_pretix_event_link_created_by_principal
                FOREIGN KEY(created_by) REFERENCES principal (id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pretix_booking (
            slug TEXT NOT NULL,
            source TEXT NOT NULL,
            source_key TEXT NOT NULL,
            state TEXT NOT NULL,
            expense_id UUID,
            error TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            id UUID DEFAULT gen_random_uuid() NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_pretix_booking PRIMARY KEY (id),
            CONSTRAINT ck_pretix_booking_source CHECK (source IN ('order','refund')),
            CONSTRAINT ck_pretix_booking_state CHECK (state IN ('booked','failed')),
            CONSTRAINT uq_pretix_booking_source UNIQUE (slug, source, source_key),
            CONSTRAINT fk_pretix_booking_expense_id_budget_expense
                FOREIGN KEY(expense_id) REFERENCES budget_expense (id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_pretix_booking_failed ON pretix_booking (state)
    """,
    """
    CREATE TABLE IF NOT EXISTS mollie_settings (
            id INTEGER NOT NULL,
            token TEXT,
            organization TEXT,
            fee_budget_id UUID,
            unassigned_budget_id UUID,
            read_ok_at TIMESTAMP WITH TIME ZONE,
            read_error TEXT,
            CONSTRAINT pk_mollie_settings PRIMARY KEY (id),
            CONSTRAINT ck_mollie_settings_singleton CHECK (id = 1),
            CONSTRAINT fk_mollie_settings_fee_budget_id_budget
                FOREIGN KEY(fee_budget_id) REFERENCES budget (id) ON DELETE SET NULL,
            CONSTRAINT fk_mollie_settings_unassigned_budget_id_budget
                FOREIGN KEY(unassigned_budget_id) REFERENCES budget (id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mollie_payment (
            id TEXT NOT NULL,
            amount NUMERIC(12, 2) NOT NULL,
            fee NUMERIC(12, 2),
            status TEXT NOT NULL,
            created TIMESTAMP WITH TIME ZONE,
            paid_at TIMESTAMP WITH TIME ZONE,
            settlement_id TEXT,
            organizer TEXT,
            event_slug TEXT,
            CONSTRAINT pk_mollie_payment PRIMARY KEY (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mollie_payment_event ON mollie_payment (organizer, event_slug)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mollie_payment_settlement_id ON mollie_payment (settlement_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS mollie_move (
            id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payment_id TEXT NOT NULL,
            amount NUMERIC(12, 2) NOT NULL,
            status TEXT NOT NULL,
            at TIMESTAMP WITH TIME ZONE,
            settlement_id TEXT,
            CONSTRAINT pk_mollie_move PRIMARY KEY (id),
            CONSTRAINT ck_mollie_move_kind CHECK (kind IN ('refund','chargeback'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mollie_move_payment_id ON mollie_move (payment_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS mollie_settlement (
            id TEXT NOT NULL,
            reference TEXT NOT NULL,
            status TEXT NOT NULL,
            settled_at TIMESTAMP WITH TIME ZONE,
            amount NUMERIC(12, 2) NOT NULL,
            fees NUMERIC(12, 2) NOT NULL,
            CONSTRAINT pk_mollie_settlement PRIMARY KEY (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mollie_booking (
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            state TEXT NOT NULL,
            expense_id UUID,
            error TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            id UUID DEFAULT gen_random_uuid() NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_mollie_booking PRIMARY KEY (id),
            CONSTRAINT ck_mollie_booking_source
                CHECK (source IN ('payment','refund','chargeback','settlement')),
            CONSTRAINT ck_mollie_booking_state CHECK (state IN ('booked','failed')),
            CONSTRAINT uq_mollie_booking_source UNIQUE (source, source_id),
            CONSTRAINT fk_mollie_booking_expense_id_budget_expense
                FOREIGN KEY(expense_id) REFERENCES budget_expense (id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mollie_booking_failed ON mollie_booking (state)
    """,
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, p.permission FROM role r "
        f"CROSS JOIN (VALUES {_PERMISSIONS}) AS p(permission) "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission IN "
    "('admin.pretix', 'admin.mollie', 'pretix.use')",
    "DROP TABLE IF EXISTS mollie_booking",
    "DROP TABLE IF EXISTS mollie_settlement",
    "DROP TABLE IF EXISTS mollie_move",
    "DROP TABLE IF EXISTS mollie_payment",
    "DROP TABLE IF EXISTS mollie_settings",
    "DROP TABLE IF EXISTS pretix_booking",
    "DROP TABLE IF EXISTS pretix_event_link",
    "DROP TABLE IF EXISTS pretix_settings",
)


def upgrade() -> None:
    """Create the tables of pretix and Mollie and grant the permissions to the admin."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Drop the tables of pretix and Mollie and the permissions."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
