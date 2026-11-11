"""event_times: the start time and the end time of an Event.

``todo_card_event.start_time`` and ``end_time`` are the optional times of the start day
and of the end day. The check ``times`` keeps a time with its day and the end of one
day at or after its start.

Idempotent. A fresh database already gets the columns and the check from the
``create_all`` baseline (0001), because the model sits in ``app.models``. A migrated
database gets them through ``ADD COLUMN IF NOT EXISTS`` and a guarded
``ADD CONSTRAINT``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c7d21f9a4e63"
down_revision: str | None = "a4c8e17d5f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_todo_card_event_times"


def upgrade() -> None:
    """Add the columns and the check."""
    op.execute("ALTER TABLE todo_card_event ADD COLUMN IF NOT EXISTS start_time time")
    op.execute("ALTER TABLE todo_card_event ADD COLUMN IF NOT EXISTS end_time time")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{_CHECK}') THEN
                ALTER TABLE todo_card_event ADD CONSTRAINT {_CHECK} CHECK (
                    (start_time IS NULL OR starts_on IS NOT NULL)
                    AND (end_time IS NULL OR ends_on IS NOT NULL)
                    AND (start_time IS NULL OR end_time IS NULL
                         OR ends_on > starts_on OR end_time >= start_time)
                );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Drop the check and the columns."""
    op.execute(f"ALTER TABLE todo_card_event DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute("ALTER TABLE todo_card_event DROP COLUMN IF EXISTS end_time")
    op.execute("ALTER TABLE todo_card_event DROP COLUMN IF EXISTS start_time")
