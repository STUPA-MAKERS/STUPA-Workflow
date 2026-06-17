"""status_event.at + submission_version.at → timestamptz (#tz).

Beide Spalten waren als ``TIMESTAMP WITHOUT TIME ZONE`` deklariert (Modell ohne
``DateTime(timezone=True)``), während ``func.now()`` bei Session-TimeZone=UTC die
UTC-Wanduhr schreibt. asyncpg liefert dann *naive* Werte, Pydantic serialisiert ohne
Offset, das Frontend interpretiert die ISO-Strings als Lokalzeit → Anzeige um den
lokalen UTC-Offset verschoben (1 h CET / 2 h CEST).

Fix: Spalten auf ``timestamptz`` umstellen und die bestehenden naiven Werte als UTC
interpretieren (``USING at AT TIME ZONE 'UTC'`` — entspricht dem tatsächlichen
Speicherinhalt). Danach trägt der Wire-Wert einen ``+00:00``-Offset; alle übrigen
DateTime-Spalten sind bereits tz-aware. Reversibel: downgrade dreht zurück und gibt
die UTC-Wanduhr als naive Wert zurück.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_tz_aware_status_version_at"
down_revision: str | None = "0032_fix_protocol_status_ck"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE status_event ALTER COLUMN at TYPE timestamptz "
        "USING at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE submission_version ALTER COLUMN at TYPE timestamptz "
        "USING at AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE status_event ALTER COLUMN at TYPE timestamp "
        "USING at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE submission_version ALTER COLUMN at TYPE timestamp "
        "USING at AT TIME ZONE 'UTC'"
    )
