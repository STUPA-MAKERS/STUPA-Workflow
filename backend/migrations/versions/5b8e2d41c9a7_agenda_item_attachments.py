"""Agenda item attachments: ``attachment.agenda_item_id``.

The upgrade adds ``attachment.agenda_item_id`` (``ON DELETE CASCADE`` to
``meeting_agenda_item``) with an index, and widens the owner check to
``num_nonnulls(application_id, ticket_id, ticket_note_id, todo_comment_id, comment_id,
agenda_item_id, draft_token_hash) = 1``. A file of an agenda item keeps
``application_id`` NULL, so it never shows on an application path.

Every key is named like the baseline names it, so both paths match. All steps are
idempotent. A fresh database already gets the column from the ``create_all`` baseline
(0001), because the models sit in ``app.models``.

The downgrade deletes the attachment rows of agenda items (they cannot meet the old
check; their objects stay as orphans, because a migration does not reach the object
storage), restores the old check, and drops the index and the column.

Revision ID: 5b8e2d41c9a7
Revises: a3c1e7f20b94
Create Date: 2026-11-05 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5b8e2d41c9a7"
down_revision: str | None = "a3c1e7f20b94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_XOR = "ck_attachment_draft_xor_application"

_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE attachment ADD COLUMN IF NOT EXISTS agenda_item_id uuid "
        "CONSTRAINT fk_attachment_agenda_item_id_meeting_agenda_item "
        "REFERENCES meeting_agenda_item (id) ON DELETE CASCADE"
    ),
    "CREATE INDEX IF NOT EXISTS ix_attachment_agenda_item_id ON attachment (agenda_item_id)",
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} CHECK (num_nonnulls("
        "application_id, ticket_id, ticket_note_id, todo_comment_id, comment_id, "
        "agenda_item_id, draft_token_hash) = 1)"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM attachment WHERE agenda_item_id IS NOT NULL",
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} CHECK (num_nonnulls("
        "application_id, ticket_id, ticket_note_id, todo_comment_id, comment_id, "
        "draft_token_hash) = 1)"
    ),
    "DROP INDEX IF EXISTS ix_attachment_agenda_item_id",
    "ALTER TABLE attachment DROP COLUMN IF EXISTS agenda_item_id",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
