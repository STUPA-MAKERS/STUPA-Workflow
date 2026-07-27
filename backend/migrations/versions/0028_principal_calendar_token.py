"""principal: calendar_token (iCal subscription, #ics).

Add a personal, rotatable feed token. The token authorizes the iCal
subscription to the meetings of one principal (`/api/calendar/{token}.ics`).
The value is plain text and low sensitivity. It stays NULL until the platform
issues the first token. The index is `UNIQUE`, and Postgres still accepts any
number of NULL rows. All statements are idempotent (`IF NOT EXISTS`). A fresh
schema already has the column from `create_all` (0001). On an older schema this
migration adds it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028_principal_calendar_token"
down_revision: str | None = "0027_pg_trgm_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE principal ADD COLUMN IF NOT EXISTS calendar_token text",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_principal_calendar_token "
    "ON principal (calendar_token)",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS uq_principal_calendar_token",
    "ALTER TABLE principal DROP COLUMN IF EXISTS calendar_token",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
