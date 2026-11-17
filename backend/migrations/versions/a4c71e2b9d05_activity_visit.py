"""Activity page: the table ``activity_visit`` (spec 001275).

The upgrade creates ``activity_visit``: one row per principal with the time of the last
visit of the activity page. Idempotent. A fresh database already gets the table from the
``create_all`` baseline (0001), because the model sits in ``app.models``.

The downgrade drops the table.

Revision ID: a4c71e2b9d05
Revises: 81852f245ccb
Create Date: 2026-11-17 20:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a4c71e2b9d05"
down_revision: str | None = "81852f245ccb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``activity_visit``."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_visit (
            principal_id uuid NOT NULL CONSTRAINT pk_activity_visit PRIMARY KEY
                CONSTRAINT fk_activity_visit_principal_id_principal
                REFERENCES principal (id) ON DELETE CASCADE,
            seen_at timestamp with time zone NOT NULL
        )
        """
    )


def downgrade() -> None:
    """Drop ``activity_visit``."""
    op.execute("DROP TABLE IF EXISTS activity_visit")
