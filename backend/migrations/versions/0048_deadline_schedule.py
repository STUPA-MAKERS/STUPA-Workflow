"""deadline_policy scheduling: time-of-day + timezone + recurring dates (#90).

Phase 1 of the deadline-definition redesign. Additive + idempotent:

* ``at_time`` (``"HH:MM"``) and ``timezone`` (IANA zone) snap the resolved due
  date to a wall-clock time, DST-correct; both NULL keeps the old instant
  arithmetic — no backfill needed.
* ``dates`` (JSONB list of ``"YYYY-MM-DD"``) backs the new ``recurring`` kind (a
  rolling submission window); the kind ``CheckConstraint`` is widened to allow it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0048_deadline_schedule"
down_revision: str | None = "0047_force_status_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE deadline_policy ADD COLUMN IF NOT EXISTS at_time text",
    "ALTER TABLE deadline_policy ADD COLUMN IF NOT EXISTS timezone text",
    "ALTER TABLE deadline_policy ADD COLUMN IF NOT EXISTS dates jsonb",
    "ALTER TABLE deadline_policy DROP CONSTRAINT IF EXISTS deadline_policy_kind",
    (
        "ALTER TABLE deadline_policy ADD CONSTRAINT deadline_policy_kind "
        "CHECK (kind IN ('absolute','relative_submitted','relative_changed',"
        "'recurring'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE deadline_policy DROP CONSTRAINT IF EXISTS deadline_policy_kind",
    (
        "ALTER TABLE deadline_policy ADD CONSTRAINT deadline_policy_kind "
        "CHECK (kind IN ('absolute','relative_submitted','relative_changed'))"
    ),
    "ALTER TABLE deadline_policy DROP COLUMN IF EXISTS dates",
    "ALTER TABLE deadline_policy DROP COLUMN IF EXISTS timezone",
    "ALTER TABLE deadline_policy DROP COLUMN IF EXISTS at_time",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
