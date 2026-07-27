"""Convert status_event.at and submission_version.at to timestamptz (#tz).

Both columns were `TIMESTAMP WITHOUT TIME ZONE`, because the model did not set
`DateTime(timezone=True)`. With the session time zone at UTC, `func.now()` writes the
UTC wall-clock time. asyncpg then returns naive values. Pydantic serializes them
without an offset. The frontend reads the ISO strings as local time. The display then
shifts by the local UTC offset (1 h CET, 2 h CEST).

Fix: change both columns to `timestamptz` and read the existing naive values as UTC
(`USING at AT TIME ZONE 'UTC'`). This matches the real stored content. The wire value
then carries a `+00:00` offset. All other DateTime columns are already tz-aware. The
migration is reversible. The downgrade converts back and returns the UTC wall-clock
time as a naive value.
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
