"""meeting_current_agenda_item: the agenda item the room handles now.

``meeting.current_agenda_item_id`` names the agenda item that the protokollant or
the session lead has open. The live followers and the beamer follow it over the
``meeting_state`` event. ``active_application_id`` cannot carry this, because a
free-text agenda item has no application.

Idempotent. A fresh database already gets the column from the ``create_all``
baseline (0001). A migrated database gets it through ``ADD COLUMN IF NOT EXISTS``.
A deleted agenda item clears the column.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "9c2e7d41b8f0"
down_revision: str | None = "b41d7c9e05aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS current_agenda_item_id uuid",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'meeting_current_agenda_item_id_fkey'
        ) THEN
            ALTER TABLE meeting
                ADD CONSTRAINT meeting_current_agenda_item_id_fkey
                FOREIGN KEY (current_agenda_item_id)
                REFERENCES meeting_agenda_item (id) ON DELETE SET NULL;
        END IF;
    END $$
    """,
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting DROP COLUMN IF EXISTS current_agenda_item_id",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
