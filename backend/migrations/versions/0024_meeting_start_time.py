"""meeting.start_time (#34 — geplante Uhrzeit)

Revision ID: 0024_meeting_start_time
Revises: 0023_global_flow
Create Date: 2026-06-08 00:00:24

Geplante Sitzungen tragen optional eine Uhrzeit. Idempotent (Inspector-Check).
``down_revision`` = ``0023_global_flow``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_meeting_start_time"
down_revision: str | None = "0023_global_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "meeting"
_COLUMN = "start_time"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in insp.get_table_names():
        return
    if _COLUMN not in {c["name"] for c in insp.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Time(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in insp.get_table_names():
        return
    if _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
