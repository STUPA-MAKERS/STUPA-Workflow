"""principal.active (#30 — Benutzer aktivieren/deaktivieren)

Revision ID: 0025_principal_active
Revises: 0024_meeting_start_time
Create Date: 2026-06-08 00:00:25

Deaktivierte Principals sollen sich nicht anmelden dürfen (Enforcement folgt im
auth-Modul). Default ``true``. Idempotent (Inspector-Check).
``down_revision`` = ``0024_meeting_start_time``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_principal_active"
down_revision: str | None = "0024_meeting_start_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "principal"
_COLUMN = "active"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in insp.get_table_names():
        return
    if _COLUMN not in {c["name"] for c in insp.get_columns(_TABLE)}:
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN, sa.Boolean(), nullable=False, server_default=sa.text("true")
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE not in insp.get_table_names():
        return
    if _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
