"""Tickets: the tables ``ticket``, ``ticket_note``, ``ticket_event`` and the permission.

The upgrade:

1. creates the sequence ``ticket_number_seq`` (the running ticket number, ``T-0001``).
2. creates ``ticket`` with the checks of kind, status and reporter (exactly one of
   ``reporter_principal_id`` and ``reporter_email`` until the anonymization), and the
   indexes on status, creation time and assignee.
3. creates ``ticket_note`` and ``ticket_event``; both cascade with the ticket.
4. adds ``attachment.ticket_id`` (cascade) with its index and widens the owner check
   to ``num_nonnulls(application_id, ticket_id, draft_token_hash) = 1``.
5. grants ``ticket.manage`` to the role ``admin``. The admin bypass grants it anyway;
   the row makes the role page show it.

Every key is named ``pk_<table>`` like the baseline names it, so both paths match.
All steps are idempotent. A fresh database already gets the tables, the column and
the sequence from the ``create_all`` baseline (0001), because the models sit in
``app.models``.

The downgrade deletes the ticket attachments (they cannot meet the old check; their
objects stay as orphans, because a migration does not reach the object storage),
restores the old check, drops the column, the tables, the sequence and the grant.

Revision ID: 86718c748401
Revises: 5d8e1b0c6f27
Create Date: 2026-10-15 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "86718c748401"
down_revision: str | None = "5d8e1b0c6f27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_XOR = "ck_attachment_draft_xor_application"

_UPGRADE: tuple[str, ...] = (
    "CREATE SEQUENCE IF NOT EXISTS ticket_number_seq",
    """
    CREATE TABLE IF NOT EXISTS ticket (
        id uuid CONSTRAINT pk_ticket PRIMARY KEY DEFAULT gen_random_uuid(),
        number integer NOT NULL DEFAULT nextval('ticket_number_seq'),
        kind text NOT NULL,
        title text NOT NULL,
        body text NOT NULL,
        status text NOT NULL DEFAULT 'new',
        reporter_principal_id uuid
            CONSTRAINT fk_ticket_reporter_principal_id_principal REFERENCES principal (id),
        reporter_email citext,
        assignee_id uuid CONSTRAINT fk_ticket_assignee_id_principal REFERENCES principal (id),
        duplicate_of_id uuid CONSTRAINT fk_ticket_duplicate_of_id_ticket
            REFERENCES ticket (id) ON DELETE SET NULL,
        context jsonb NOT NULL DEFAULT '{}'::jsonb,
        closed_at timestamptz,
        anonymized_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_ticket_number UNIQUE (number),
        CONSTRAINT ck_ticket_kind CHECK (kind IN ('bug', 'question', 'idea')),
        CONSTRAINT ck_ticket_status
            CHECK (status IN ('new', 'in_progress', 'done', 'rejected')),
        CONSTRAINT ck_ticket_reporter CHECK (
            anonymized_at IS NOT NULL
            OR num_nonnulls(reporter_principal_id, reporter_email) = 1
        )
    )
    """,
    "ALTER SEQUENCE ticket_number_seq OWNED BY ticket.number",
    "CREATE INDEX IF NOT EXISTS ix_ticket_status ON ticket (status)",
    "CREATE INDEX IF NOT EXISTS ix_ticket_created_at ON ticket (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ticket_assignee ON ticket (assignee_id)",
    """
    CREATE TABLE IF NOT EXISTS ticket_note (
        id uuid CONSTRAINT pk_ticket_note PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id uuid NOT NULL
            CONSTRAINT fk_ticket_note_ticket_id_ticket REFERENCES ticket (id) ON DELETE CASCADE,
        author_id uuid NOT NULL
            CONSTRAINT fk_ticket_note_author_id_principal REFERENCES principal (id),
        body text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        edited_at timestamptz,
        deleted_at timestamptz
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ticket_note_ticket_id ON ticket_note (ticket_id)",
    """
    CREATE TABLE IF NOT EXISTS ticket_event (
        id uuid CONSTRAINT pk_ticket_event PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id uuid NOT NULL
            CONSTRAINT fk_ticket_event_ticket_id_ticket REFERENCES ticket (id) ON DELETE CASCADE,
        actor_id uuid CONSTRAINT fk_ticket_event_actor_id_principal REFERENCES principal (id),
        kind text NOT NULL,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_ticket_event_kind
            CHECK (kind IN ('created', 'status', 'assignee', 'kind', 'todo_done'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ticket_event_ticket_id ON ticket_event (ticket_id)",
    (
        "ALTER TABLE attachment ADD COLUMN IF NOT EXISTS ticket_id uuid "
        "CONSTRAINT fk_attachment_ticket_id_ticket REFERENCES ticket (id) ON DELETE CASCADE"
    ),
    "CREATE INDEX IF NOT EXISTS ix_attachment_ticket_id ON attachment (ticket_id)",
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} "
        "CHECK (num_nonnulls(application_id, ticket_id, draft_token_hash) = 1)"
    ),
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'ticket.manage' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'ticket.manage'",
    "DELETE FROM attachment WHERE ticket_id IS NOT NULL",
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} "
        "CHECK (num_nonnulls(application_id, draft_token_hash) = 1)"
    ),
    "DROP INDEX IF EXISTS ix_attachment_ticket_id",
    "ALTER TABLE attachment DROP COLUMN IF EXISTS ticket_id",
    "DROP TABLE IF EXISTS ticket_event",
    "DROP TABLE IF EXISTS ticket_note",
    "DROP TABLE IF EXISTS ticket",
    "DROP SEQUENCE IF EXISTS ticket_number_seq",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
