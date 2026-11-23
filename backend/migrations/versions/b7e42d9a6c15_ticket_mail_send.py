"""Tickets: the send of a mail, the signature and the confirmation of a Postfach.

The upgrade:

1. adds ``ticket_mailbox.signature``, the text that ends each sent mail, and
   ``ticket_mailbox.confirm``, the switch "Eingang bestätigen".
2. adds the columns of a sent mail to ``ticket_mail``: ``to_addresses``, ``state``
   (``sending``, ``sent`` or ``failed``), ``attempts``, ``send_error`` and
   ``next_try_at``. An imported mail has no state.
3. adds a partial index for the mails that wait for the worker.

All steps are idempotent. A fresh database already gets the columns from the
``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade removes the columns. A mail that waits for its send is then never sent.

Revision ID: b7e42d9a6c15
Revises: f3a17c5e9b24
Create Date: 2026-11-23 21:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b7e42d9a6c15"
down_revision: str | None = "f3a17c5e9b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE ticket_mailbox ADD COLUMN IF NOT EXISTS signature text NOT NULL DEFAULT ''",
    "ALTER TABLE ticket_mailbox ADD COLUMN IF NOT EXISTS confirm boolean NOT NULL DEFAULT false",
    "ALTER TABLE ticket_mail ADD COLUMN IF NOT EXISTS to_addresses jsonb "
    "NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE ticket_mail ADD COLUMN IF NOT EXISTS state text",
    "ALTER TABLE ticket_mail ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0",
    "ALTER TABLE ticket_mail ADD COLUMN IF NOT EXISTS send_error text",
    "ALTER TABLE ticket_mail ADD COLUMN IF NOT EXISTS next_try_at timestamptz",
    "ALTER TABLE ticket_mail DROP CONSTRAINT IF EXISTS ck_ticket_mail_state",
    "ALTER TABLE ticket_mail ADD CONSTRAINT ck_ticket_mail_state "
    "CHECK (state IS NULL OR state IN ('sending', 'sent', 'failed'))",
    "CREATE INDEX IF NOT EXISTS ix_ticket_mail_sending ON ticket_mail (next_try_at) "
    "WHERE state = 'sending'",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_ticket_mail_sending",
    "ALTER TABLE ticket_mail DROP CONSTRAINT IF EXISTS ck_ticket_mail_state",
    "ALTER TABLE ticket_mail DROP COLUMN IF EXISTS next_try_at",
    "ALTER TABLE ticket_mail DROP COLUMN IF EXISTS send_error",
    "ALTER TABLE ticket_mail DROP COLUMN IF EXISTS attempts",
    "ALTER TABLE ticket_mail DROP COLUMN IF EXISTS state",
    "ALTER TABLE ticket_mail DROP COLUMN IF EXISTS to_addresses",
    "ALTER TABLE ticket_mailbox DROP COLUMN IF EXISTS confirm",
    "ALTER TABLE ticket_mailbox DROP COLUMN IF EXISTS signature",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
