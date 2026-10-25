"""Chat attachments and blocked senders: three attachment owners, ``ticket_sender_block``.

The upgrade:

1. adds ``attachment.ticket_note_id``, ``attachment.todo_comment_id`` and
   ``attachment.comment_id`` (each ``ON DELETE CASCADE``) with an index each, and
   widens the owner check to ``num_nonnulls(application_id, ticket_id,
   ticket_note_id, todo_comment_id, comment_id, draft_token_hash) = 1``. A file of a
   chat message keeps ``application_id`` NULL, so it never shows on an application
   path.
2. creates ``ticket_sender_block``: exactly one of ``principal_id`` (cascade) and
   ``email`` (stored lowercase), the source ticket (``SET NULL``), the blocking
   person (``SET NULL``), the time, ``hit_count`` and ``last_hit_at``, with a partial
   unique index on each target.

Every key is named like the baseline names it, so both paths match. All steps are
idempotent. A fresh database already gets the columns and the table from the
``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade deletes the attachment rows of the three new owners (they cannot meet
the old check; their objects stay as orphans, because a migration does not reach the
object storage), restores the old check, drops the indexes, the columns and the table.

Revision ID: 269d13cd80a8
Revises: 59ccfd0a0856
Create Date: 2026-10-16 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "269d13cd80a8"
down_revision: str | None = "59ccfd0a0856"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_XOR = "ck_attachment_draft_xor_application"

#: (column, referenced table) of the new owners of an attachment.
_OWNERS: tuple[tuple[str, str], ...] = (
    ("ticket_note_id", "ticket_note"),
    ("todo_comment_id", "todo_comment"),
    ("comment_id", "comment"),
)

_UPGRADE: tuple[str, ...] = (
    *(
        stmt
        for column, table in _OWNERS
        for stmt in (
            (
                f"ALTER TABLE attachment ADD COLUMN IF NOT EXISTS {column} uuid "
                f"CONSTRAINT fk_attachment_{column}_{table} "
                f"REFERENCES {table} (id) ON DELETE CASCADE"
            ),
            f"CREATE INDEX IF NOT EXISTS ix_attachment_{column} ON attachment ({column})",
        )
    ),
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} CHECK (num_nonnulls("
        "application_id, ticket_id, ticket_note_id, todo_comment_id, comment_id, "
        "draft_token_hash) = 1)"
    ),
    """
    CREATE TABLE IF NOT EXISTS ticket_sender_block (
        id uuid CONSTRAINT pk_ticket_sender_block PRIMARY KEY DEFAULT gen_random_uuid(),
        principal_id uuid CONSTRAINT fk_ticket_sender_block_principal_id_principal
            REFERENCES principal (id) ON DELETE CASCADE,
        email text,
        source_ticket_id uuid CONSTRAINT fk_ticket_sender_block_source_ticket_id_ticket
            REFERENCES ticket (id) ON DELETE SET NULL,
        created_by uuid CONSTRAINT fk_ticket_sender_block_created_by_principal
            REFERENCES principal (id) ON DELETE SET NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        hit_count integer NOT NULL DEFAULT 0,
        last_hit_at timestamptz,
        CONSTRAINT ck_ticket_sender_block_target CHECK (num_nonnulls(principal_id, email) = 1),
        CONSTRAINT ck_ticket_sender_block_email_lower
            CHECK (email IS NULL OR email = lower(email))
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_sender_block_principal "
        "ON ticket_sender_block (principal_id) WHERE principal_id IS NOT NULL"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_sender_block_email "
        "ON ticket_sender_block (email) WHERE email IS NOT NULL"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS ticket_sender_block",
    (
        "DELETE FROM attachment WHERE ticket_note_id IS NOT NULL "
        "OR todo_comment_id IS NOT NULL OR comment_id IS NOT NULL"
    ),
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} "
        "CHECK (num_nonnulls(application_id, ticket_id, draft_token_hash) = 1)"
    ),
    *(
        stmt
        for column, _table in _OWNERS
        for stmt in (
            f"DROP INDEX IF EXISTS ix_attachment_{column}",
            f"ALTER TABLE attachment DROP COLUMN IF EXISTS {column}",
        )
    ),
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
