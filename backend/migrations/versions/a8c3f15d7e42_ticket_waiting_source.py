"""Tickets: the status ``waiting``, the source, the follow-up and the switch ``in_app``.

The upgrade:

1. widens the check of the ticket status by ``waiting`` (Wartet auf Antwort).
2. adds ``ticket.source``. Each existing ticket came from the help menu, so the default
   ``help`` is its source.
3. adds ``ticket.follow_up_of_id``, the closed ticket that a late message of the sender
   answered.
4. adds ``ticket_area.in_app``, the switch that lets a signed-in person choose the
   Bereich in the ticket dialog of the help menu.

All steps are idempotent. A fresh database already gets the columns from the
``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade sets each waiting ticket to ``in_progress``, because the older schema has
no such status, and removes the columns.

Revision ID: a8c3f15d7e42
Revises: e41b7d90a6c2
Create Date: 2026-11-23 17:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a8c3f15d7e42"
down_revision: str | None = "e41b7d90a6c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "'new', 'in_progress', 'done', 'rejected'"

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE ticket DROP CONSTRAINT IF EXISTS ck_ticket_status",
    "ALTER TABLE ticket ADD CONSTRAINT ck_ticket_status "
    f"CHECK (status IN ({_STATUSES}, 'waiting'))",
    "ALTER TABLE ticket ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'help'",
    "ALTER TABLE ticket DROP CONSTRAINT IF EXISTS ck_ticket_source",
    "ALTER TABLE ticket ADD CONSTRAINT ck_ticket_source CHECK (source IN ('help', 'mail', 'team'))",
    "ALTER TABLE ticket ADD COLUMN IF NOT EXISTS follow_up_of_id uuid",
    "ALTER TABLE ticket DROP CONSTRAINT IF EXISTS fk_ticket_follow_up_of_id_ticket",
    "ALTER TABLE ticket ADD CONSTRAINT fk_ticket_follow_up_of_id_ticket "
    "FOREIGN KEY (follow_up_of_id) REFERENCES ticket (id) ON DELETE SET NULL",
    "ALTER TABLE ticket_area ADD COLUMN IF NOT EXISTS in_app boolean NOT NULL DEFAULT false",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE ticket_area DROP COLUMN IF EXISTS in_app",
    "ALTER TABLE ticket DROP COLUMN IF EXISTS follow_up_of_id",
    "ALTER TABLE ticket DROP COLUMN IF EXISTS source",
    "UPDATE ticket SET status = 'in_progress' WHERE status = 'waiting'",
    "ALTER TABLE ticket DROP CONSTRAINT IF EXISTS ck_ticket_status",
    f"ALTER TABLE ticket ADD CONSTRAINT ck_ticket_status CHECK (status IN ({_STATUSES}))",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
