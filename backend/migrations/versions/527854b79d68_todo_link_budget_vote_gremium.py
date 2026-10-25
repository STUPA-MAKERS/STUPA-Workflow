"""todo_link_budget_vote_gremium: a card links to a vote, a gremium, an invoice, a booking.

The upgrade adds four target columns to ``todo_link`` (``ON DELETE CASCADE``):
``vote_id`` → ``vote``, ``gremium_id`` → ``gremium``, ``invoice_id`` → ``invoice`` and
``expense_id`` → ``budget_expense``. Each gets the partial unique index
``uq_todo_link_<column>`` (one link per card and target) and the partial lookup index
``ix_todo_link_<column>`` (the back-references). ``ck_todo_link_one_target`` counts
the new columns too, in the column order of ``LINK_COLUMNS``.

Idempotent. A fresh database already gets the columns from the ``create_all``
baseline (0001), because ``TodoLink`` sits in ``app.models``. A migrated database gets
them through ``ADD COLUMN IF NOT EXISTS``; the check is dropped and added again.

The downgrade deletes the links of the new kinds (the old check refuses them), drops
the indexes and the columns and restores the old check.

Revision ID: 527854b79d68
Revises: 066ff25554e2
Create Date: 2026-10-17 07:11:17.060311
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "527854b79d68"
down_revision: str | None = "066ff25554e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The new target columns and the tables they reference.
_NEW: tuple[tuple[str, str], ...] = (
    ("vote_id", "vote"),
    ("gremium_id", "gremium"),
    ("invoice_id", "invoice"),
    ("expense_id", "budget_expense"),
)

_OLD_TARGETS = "application_id, meeting_id, agenda_item_id, ticket_id, todo_id"
_NEW_TARGETS = (
    "application_id, meeting_id, agenda_item_id, vote_id, gremium_id, invoice_id, "
    "expense_id, ticket_id, todo_id"
)


def _check(targets: str) -> tuple[str, ...]:
    return (
        "ALTER TABLE todo_link DROP CONSTRAINT IF EXISTS ck_todo_link_one_target",
        "ALTER TABLE todo_link ADD CONSTRAINT ck_todo_link_one_target "
        f"CHECK (num_nonnulls({targets}) = 1)",
    )


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for column, table in _NEW:
        op.execute(
            f"ALTER TABLE todo_link ADD COLUMN IF NOT EXISTS {column} uuid "
            f"CONSTRAINT fk_todo_link_{column}_{table} "
            f"REFERENCES {table} (id) ON DELETE CASCADE"
        )
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_link_{column} "
            f"ON todo_link (card_id, {column}) WHERE {column} IS NOT NULL"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_todo_link_{column} "
            f"ON todo_link ({column}) WHERE {column} IS NOT NULL"
        )
    for stmt in _check(_NEW_TARGETS):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    present = " OR ".join(f"{column} IS NOT NULL" for column, _ in _NEW)
    op.execute(f"DELETE FROM todo_link WHERE {present}")
    for stmt in _check(_OLD_TARGETS):
        op.execute(stmt)
    for column, _ in _NEW:
        op.execute(f"DROP INDEX IF EXISTS ix_todo_link_{column}")
        op.execute(f"DROP INDEX IF EXISTS uq_todo_link_{column}")
        op.execute(f"ALTER TABLE todo_link DROP COLUMN IF EXISTS {column}")
