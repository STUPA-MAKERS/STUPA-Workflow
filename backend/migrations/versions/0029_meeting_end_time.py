"""meeting: end_time (#ics).

Optionale End-Uhrzeit einer Sitzung (ergänzt ``start_time``). Wird im iCal-Abo als
``DTEND`` genutzt; fehlt sie, nimmt der Feed 1 h Default-Dauer an. Nullable, idempotent
(``IF NOT EXISTS``) — auf frischem Schema bereits via ``create_all`` (0001) vorhanden.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029_meeting_end_time"
down_revision: str | None = "0028_principal_calendar_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE meeting ADD COLUMN IF NOT EXISTS end_time time")


def downgrade() -> None:
    op.execute("ALTER TABLE meeting DROP COLUMN IF EXISTS end_time")
