"""Bestellungen: the Bestellung as an owner of an attachment.

The upgrade adds ``attachment.order_id`` (``ON DELETE CASCADE``) with its index and widens
the owner check to ``num_nonnulls(application_id, ticket_id, ticket_note_id,
todo_comment_id, comment_id, order_id, draft_token_hash) = 1``. A file of a Bestellung keeps
``application_id`` NULL, so no path of the Antrag shows it.

Every key is named like the baseline names it, so both paths match. All steps are
idempotent, because a fresh database gets the column from the ``create_all`` baseline (0001).

The downgrade deletes the attachment rows of the Bestellungen, because they cannot meet the
old check. Their objects stay as orphans, because a migration does not reach the object
storage. It then restores the old check and drops the index and the column.

Revision ID: c41b9e62d7a3
Revises: e7d870f703d5
Create Date: 2026-11-24 20:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c41b9e62d7a3"
down_revision: str | None = "e7d870f703d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_XOR = "ck_attachment_draft_xor_application"
_OLD_OWNERS = "application_id, ticket_id, ticket_note_id, todo_comment_id, comment_id"

_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE attachment ADD COLUMN IF NOT EXISTS order_id uuid "
        "CONSTRAINT fk_attachment_order_id_purchase_order "
        "REFERENCES purchase_order (id) ON DELETE CASCADE"
    ),
    "CREATE INDEX IF NOT EXISTS ix_attachment_order_id ON attachment (order_id)",
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} "
        f"CHECK (num_nonnulls({_OLD_OWNERS}, order_id, draft_token_hash) = 1)"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM attachment WHERE order_id IS NOT NULL",
    f"ALTER TABLE attachment DROP CONSTRAINT IF EXISTS {_XOR}",
    (
        f"ALTER TABLE attachment ADD CONSTRAINT {_XOR} "
        f"CHECK (num_nonnulls({_OLD_OWNERS}, draft_token_hash) = 1)"
    ),
    "DROP INDEX IF EXISTS ix_attachment_order_id",
    "ALTER TABLE attachment DROP COLUMN IF EXISTS order_id",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
