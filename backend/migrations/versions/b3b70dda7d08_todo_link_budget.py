"""todo_link_budget: a card links to a cost centre (spec 000552).

The upgrade adds the target column ``budget_id`` → ``budget`` (``ON DELETE CASCADE``) to
``todo_link``, with the partial unique index ``uq_todo_link_budget_id`` (one link per card
and cost centre) and the partial lookup index ``ix_todo_link_budget_id`` (the
back-references). ``ck_todo_link_one_target`` counts the new column too, in the column
order of ``LINK_COLUMNS``.

Idempotent. A fresh database already gets the column from the ``create_all`` baseline
(0001), because ``TodoLink`` sits in ``app.models``. A migrated database gets it through
``ADD COLUMN IF NOT EXISTS``; the check is dropped and added again.

The downgrade deletes the cost centre links (the old check refuses them), drops the indexes
and the column and restores the old check.

Revision ID: b3b70dda7d08
Revises: db31a12f701e
Create Date: 2026-11-09 10:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b3b70dda7d08"
down_revision: str | None = "db31a12f701e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TARGETS = (
    "application_id, meeting_id, agenda_item_id, vote_id, gremium_id, invoice_id, "
    "expense_id, ticket_id, todo_id"
)
_NEW_TARGETS = (
    "application_id, meeting_id, agenda_item_id, vote_id, gremium_id, invoice_id, "
    "expense_id, budget_id, ticket_id, todo_id"
)


def _check(targets: str) -> tuple[str, ...]:
    return (
        "ALTER TABLE todo_link DROP CONSTRAINT IF EXISTS ck_todo_link_one_target",
        "ALTER TABLE todo_link ADD CONSTRAINT ck_todo_link_one_target "
        f"CHECK (num_nonnulls({targets}) = 1)",
    )


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(
        "ALTER TABLE todo_link ADD COLUMN IF NOT EXISTS budget_id uuid "
        "CONSTRAINT fk_todo_link_budget_id_budget "
        "REFERENCES budget (id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_link_budget_id "
        "ON todo_link (card_id, budget_id) WHERE budget_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_todo_link_budget_id "
        "ON todo_link (budget_id) WHERE budget_id IS NOT NULL"
    )
    for stmt in _check(_NEW_TARGETS):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    op.execute("DELETE FROM todo_link WHERE budget_id IS NOT NULL")
    for stmt in _check(_OLD_TARGETS):
        op.execute(stmt)
    op.execute("DROP INDEX IF EXISTS ix_todo_link_budget_id")
    op.execute("DROP INDEX IF EXISTS uq_todo_link_budget_id")
    op.execute("ALTER TABLE todo_link DROP COLUMN IF EXISTS budget_id")
