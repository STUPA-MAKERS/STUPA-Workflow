"""Tickets: the Postfach of a Bereich and the permission ``admin.ticket_mail``.

The upgrade:

1. creates ``ticket_mailbox``: at most one Postfach for each Bereich, with the address,
   the IMAP and the SMTP account, the folder for done mails, the switch and the state of
   the fetch.
2. grants ``admin.ticket_mail`` to the ``admin`` role.

All steps are idempotent. A fresh database already gets the table from the
``create_all`` baseline (0001), because the model sits in ``app.models``.

Revision ID: d2f6b9a41c37
Revises: a8c3f15d7e42
Create Date: 2026-11-23 18:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d2f6b9a41c37"
down_revision: str | None = "a8c3f15d7e42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS ticket_mailbox (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        area_id uuid NOT NULL,
        address citext NOT NULL,
        imap_host text NOT NULL,
        imap_port integer NOT NULL,
        imap_user text NOT NULL,
        imap_password text NOT NULL,
        smtp_host text NOT NULL,
        smtp_port integer NOT NULL,
        smtp_user text NOT NULL,
        smtp_password text NOT NULL,
        done_folder text NOT NULL,
        enabled boolean NOT NULL DEFAULT false,
        uid_validity bigint,
        last_uid bigint NOT NULL DEFAULT 0,
        failures integer NOT NULL DEFAULT 0,
        last_error text,
        fetched_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_ticket_mailbox PRIMARY KEY (id),
        CONSTRAINT uq_ticket_mailbox_area_id UNIQUE (area_id),
        CONSTRAINT fk_ticket_mailbox_area_id_ticket_area FOREIGN KEY (area_id)
            REFERENCES ticket_area (id) ON DELETE CASCADE
    )
    """,
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'admin.ticket_mail' FROM role r WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'admin.ticket_mail'",
    "DROP TABLE IF EXISTS ticket_mailbox",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
