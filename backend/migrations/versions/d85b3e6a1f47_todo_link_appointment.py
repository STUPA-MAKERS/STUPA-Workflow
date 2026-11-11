"""todo_link_appointment: a card links a Termin.

``todo_link.appointment_id`` points a card at a Termin (``calendar_appointment``). The
column gets the two indexes of every target column: ``uq_todo_link_appointment_id``
(one link per card and Termin) and ``ix_todo_link_appointment_id`` (the
back-references). ``ck_todo_link_one_target`` counts the new column too.

Idempotent. A fresh database already gets the column from the ``create_all`` baseline
(0001), because the model sits in ``app.models``. A migrated database gets it through
``ADD COLUMN IF NOT EXISTS``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d85b3e6a1f47"
down_revision: str | None = "c7d21f9a4e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TARGETS = (
    "application_id, meeting_id, agenda_item_id, vote_id, gremium_id, invoice_id, "
    "expense_id, budget_id, ticket_id, todo_id"
)
_NEW_TARGETS = (
    "application_id, meeting_id, agenda_item_id, vote_id, appointment_id, gremium_id, "
    "invoice_id, expense_id, budget_id, ticket_id, todo_id"
)


def _check(targets: str) -> tuple[str, ...]:
    return (
        "ALTER TABLE todo_link DROP CONSTRAINT IF EXISTS ck_todo_link_one_target",
        "ALTER TABLE todo_link ADD CONSTRAINT ck_todo_link_one_target "
        f"CHECK (num_nonnulls({targets}) = 1)",
    )


def upgrade() -> None:
    """Add the column, its indexes and the new check."""
    op.execute(
        "ALTER TABLE todo_link ADD COLUMN IF NOT EXISTS appointment_id uuid "
        "CONSTRAINT fk_todo_link_appointment_id_calendar_appointment "
        "REFERENCES calendar_appointment (id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_link_appointment_id "
        "ON todo_link (card_id, appointment_id) WHERE appointment_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_todo_link_appointment_id "
        "ON todo_link (appointment_id) WHERE appointment_id IS NOT NULL"
    )
    for stmt in _check(_NEW_TARGETS):
        op.execute(stmt)


def downgrade() -> None:
    """Delete the links to Termine and drop the column."""
    op.execute("DELETE FROM todo_link WHERE appointment_id IS NOT NULL")
    for stmt in _check(_OLD_TARGETS):
        op.execute(stmt)
    op.execute("DROP INDEX IF EXISTS ix_todo_link_appointment_id")
    op.execute("DROP INDEX IF EXISTS uq_todo_link_appointment_id")
    op.execute("ALTER TABLE todo_link DROP COLUMN IF EXISTS appointment_id")
