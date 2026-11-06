"""todo_events: a card can be an Event (Veranstaltung), and an Event can belong to a series.

Idempotent. A fresh database gets the tables from `create_all` (baseline), so this
migration is a no-op there. A migrated database gets them here.

* `todo_event_series`: a series (`Reihe`). The name is unique in the platform
  (`lower(name)`), and a series belongs to no board.
* `todo_card_event`: the event data of a card, 1:1 by `card_id`. A card with a row is an
  Event. The end needs a start and is not before it.

Revision ID: 84414cd99f16
Revises: c71e5a0d9f42
Create Date: 2026-11-06 12:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "84414cd99f16"
down_revision: str | None = "c71e5a0d9f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS todo_event_series (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        name text NOT NULL,
        created_by uuid REFERENCES principal(id) ON DELETE SET NULL,
        CONSTRAINT ck_todo_event_series_name CHECK (length(btrim(name)) BETWEEN 1 AND 200)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_todo_event_series_name "
    "ON todo_event_series (lower(name))",
    """
    CREATE TABLE IF NOT EXISTS todo_card_event (
        card_id uuid PRIMARY KEY REFERENCES todo_card(id) ON DELETE CASCADE,
        starts_on date,
        ends_on date,
        place text,
        participants integer,
        series_id uuid REFERENCES todo_event_series(id) ON DELETE SET NULL,
        CONSTRAINT ck_todo_card_event_dates
            CHECK (ends_on IS NULL OR (starts_on IS NOT NULL AND ends_on >= starts_on)),
        CONSTRAINT ck_todo_card_event_participants
            CHECK (participants IS NULL OR participants >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_todo_card_event_series_id ON todo_card_event (series_id)",
    "CREATE INDEX IF NOT EXISTS ix_todo_card_event_starts_on ON todo_card_event (starts_on)",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS todo_card_event",
    "DROP TABLE IF EXISTS todo_event_series",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
