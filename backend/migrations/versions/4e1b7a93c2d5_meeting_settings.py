"""Meeting settings: the open window of a meeting.

The upgrade creates the single-row table ``meeting_settings`` and inserts the row
``(id=1, open_lead_minutes=60, confirm_lead_minutes=10)``. A meeting opens at the
earliest 60 minutes before its planned start, and up to 10 minutes before the start
the open needs an extra confirmation. The deadlines page changes both values.

The statements are idempotent. A fresh database gets the table from the
``create_all`` baseline (0001), because the model already declares it.

The downgrade drops the table.

Revision ID: 4e1b7a93c2d5
Revises: 7c1e4a9b2d63
Create Date: 2026-10-12 16:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "4e1b7a93c2d5"
down_revision: str | None = "7c1e4a9b2d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS meeting_settings (
    id integer NOT NULL DEFAULT 1,
    open_lead_minutes integer NOT NULL DEFAULT 60,
    confirm_lead_minutes integer NOT NULL DEFAULT 10,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NULL,
    CONSTRAINT pk_meeting_settings PRIMARY KEY (id),
    CONSTRAINT ck_meeting_settings_singleton CHECK (id = 1),
    CONSTRAINT ck_meeting_settings_open_lead
        CHECK (open_lead_minutes BETWEEN 0 AND 10080),
    CONSTRAINT ck_meeting_settings_confirm_lead
        CHECK (confirm_lead_minutes BETWEEN 0 AND open_lead_minutes)
)
"""

_SEED = """
INSERT INTO meeting_settings (id, open_lead_minutes, confirm_lead_minutes)
VALUES (1, 60, 10)
ON CONFLICT (id) DO NOTHING
"""


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(_CREATE_TABLE)
    op.execute(_SEED)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    op.execute("DROP TABLE IF EXISTS meeting_settings")
