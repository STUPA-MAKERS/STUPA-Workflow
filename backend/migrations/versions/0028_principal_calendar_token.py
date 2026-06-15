"""principal: calendar_token (iCal-Abo, #ics).

Persönlicher, rotierbarer Feed-Token für das iCal-Abo der eigenen Sitzungen
(``/api/calendar/{token}.ics``). Klartext (low-sensitivity), nullable bis zur
ersten Ausgabe; ``UNIQUE`` (Postgres lässt beliebig viele NULLs zu). Idempotent
(``IF NOT EXISTS``) — auf frischem Schema ist die Spalte bereits via
``create_all`` (0001) vorhanden, auf älteren Schemata legt sie diese Migration an.
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
