"""Tickets: the mails of a ticket and the name of the sender.

The upgrade:

1. adds ``ticket.reporter_name``, the display name of ``From`` of a ticket from a mail.
2. creates ``ticket_mail``. A row is one imported or sent mail of a ticket. The unique
   pair of Postfach and ``Message-ID`` is the identity of a mail.
3. widens the check of the event kind by ``mail_auto``, the event of an automatic mail.

All steps are idempotent. A fresh database already gets the table and the column from
the ``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade deletes each ``mail_auto`` event, because the older schema has no such
kind, and removes the table and the column. The sources of the mails stay in the object
storage.

Revision ID: f3a17c5e9b24
Revises: d2f6b9a41c37
Create Date: 2026-11-23 19:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f3a17c5e9b24"
down_revision: str | None = "d2f6b9a41c37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'created', 'status', 'assignee', 'kind', 'todo_done', 'category', 'area'"

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE ticket ADD COLUMN IF NOT EXISTS reporter_name text",
    """
    CREATE TABLE IF NOT EXISTS ticket_mail (
        id uuid NOT NULL DEFAULT gen_random_uuid(),
        mailbox_id uuid,
        ticket_id uuid NOT NULL,
        note_id uuid,
        direction text NOT NULL DEFAULT 'in',
        message_id text NOT NULL,
        from_address citext,
        from_name text,
        cc jsonb NOT NULL DEFAULT '[]'::jsonb,
        subject text,
        source_key text,
        source_size bigint NOT NULL DEFAULT 0,
        source_scan text,
        skipped jsonb NOT NULL DEFAULT '[]'::jsonb,
        automatic boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_ticket_mail PRIMARY KEY (id),
        CONSTRAINT ck_ticket_mail_direction CHECK (direction IN ('in', 'out')),
        CONSTRAINT uq_ticket_mail_mailbox_message UNIQUE (mailbox_id, message_id),
        CONSTRAINT fk_ticket_mail_mailbox_id_ticket_mailbox FOREIGN KEY (mailbox_id)
            REFERENCES ticket_mailbox (id) ON DELETE SET NULL,
        CONSTRAINT fk_ticket_mail_ticket_id_ticket FOREIGN KEY (ticket_id)
            REFERENCES ticket (id) ON DELETE CASCADE,
        CONSTRAINT fk_ticket_mail_note_id_ticket_note FOREIGN KEY (note_id)
            REFERENCES ticket_note (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ticket_mail_ticket_id ON ticket_mail (ticket_id)",
    "CREATE INDEX IF NOT EXISTS ix_ticket_mail_message_id ON ticket_mail (message_id)",
    "ALTER TABLE ticket_event DROP CONSTRAINT IF EXISTS ck_ticket_event_kind",
    f"ALTER TABLE ticket_event ADD CONSTRAINT ck_ticket_event_kind "
    f"CHECK (kind IN ({_KINDS}, 'mail_auto'))",
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM ticket_event WHERE kind = 'mail_auto'",
    "ALTER TABLE ticket_event DROP CONSTRAINT IF EXISTS ck_ticket_event_kind",
    f"ALTER TABLE ticket_event ADD CONSTRAINT ck_ticket_event_kind CHECK (kind IN ({_KINDS}))",
    "DROP TABLE IF EXISTS ticket_mail",
    "ALTER TABLE ticket DROP COLUMN IF EXISTS reporter_name",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
