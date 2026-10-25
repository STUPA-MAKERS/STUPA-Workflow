"""@-mentions in the shared chat: ``comment.mentions`` and ``ticket_note.mentions``.

The upgrade adds the column ``mentions`` (JSONB, ``NOT NULL``, default ``'[]'``) to
the application comments (``comment``) and to the ticket notes (``ticket_note``). The
column holds the principal ids of the mentioned persons as strings, like
``todo_comment.mentions``. Every existing message mentions nobody, so the default
fills it.

Both steps are idempotent. A fresh database already gets the columns from the
``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade drops both columns.

Revision ID: e7eeac24423f
Revises: 199cc9a409f2
Create Date: 2026-10-17 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e7eeac24423f"
down_revision: str | None = "199cc9a409f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES: tuple[str, ...] = ("comment", "ticket_note")


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS mentions jsonb "
            "NOT NULL DEFAULT '[]'::jsonb"
        )


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS mentions")
