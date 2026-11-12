"""calendar_public: the switch "Öffentlich" of a Termin.

``calendar_appointment.public`` marks a Termin that the public calendar shows without a
sign-in.

Idempotent. A fresh database already gets the column from the ``create_all`` baseline
(0001), because the model sits in ``app.models``. A migrated database gets it through
``ADD COLUMN IF NOT EXISTS``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a4c8e17d5f02"
down_revision: str | None = "e3a63975be4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column."""
    op.execute(
        "ALTER TABLE calendar_appointment "
        "ADD COLUMN IF NOT EXISTS public boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    """Drop the column."""
    op.execute("ALTER TABLE calendar_appointment DROP COLUMN IF EXISTS public")
