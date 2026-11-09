"""state_outcome_flags: approved and denied are flags on a flow state (specs 000571/000572).

The upgrade adds ``state.is_approved`` and ``state.is_denied`` with the checks
``ck_state_state_one_outcome`` (never both) and ``ck_state_state_outcome_normal`` (never on a
vote state). It then sets the flags from the old lists on the top cost centres:
a normal state whose key is in some ``accepted_state_keys`` becomes approved, one whose key
is in some ``denied_state_keys`` becomes denied. A key in both lists gets neither flag, and
the migration continues with the next state, because a conflict must not stop a deploy
(spec 000572). Last, it drops ``budget.accepted_state_keys`` and
``budget.denied_state_keys``.

Idempotent. A fresh database already gets the columns from the ``create_all`` baseline
(0001), so every step uses ``IF EXISTS`` / ``IF NOT EXISTS``, and the data step runs only
while the old columns exist.

The downgrade adds the lists again and writes the flagged keys of all states into every top
cost centre, then drops the flags.

Revision ID: e4a91c27b6d3
Revises: b3b70dda7d08
Create Date: 2026-11-09 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a91c27b6d3"
down_revision: str | None = "b3b70dda7d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = """
    SELECT DISTINCT jsonb_array_elements_text(
        CASE WHEN jsonb_typeof({col}) = 'array' THEN {col} ELSE '[]'::jsonb END
    ) AS key
    FROM budget WHERE parent_id IS NULL
"""


def _old_lists_exist() -> bool:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'budget' "
                "AND column_name IN ('accepted_state_keys', 'denied_state_keys')"
            )
        )
        .scalar_one()
    )
    return row == 2


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(
        "ALTER TABLE state ADD COLUMN IF NOT EXISTS is_approved boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE state ADD COLUMN IF NOT EXISTS is_denied boolean NOT NULL DEFAULT false"
    )
    if _old_lists_exist():
        accepted = _KEYS.format(col="accepted_state_keys")
        denied = _KEYS.format(col="denied_state_keys")
        op.execute(
            f"UPDATE state SET is_approved = true WHERE kind = 'normal' "
            f"AND key IN ({accepted}) AND key NOT IN ({denied})"
        )
        op.execute(
            f"UPDATE state SET is_denied = true WHERE kind = 'normal' "
            f"AND key IN ({denied}) AND key NOT IN ({accepted})"
        )
    op.execute("ALTER TABLE state DROP CONSTRAINT IF EXISTS ck_state_state_one_outcome")
    op.execute(
        "ALTER TABLE state ADD CONSTRAINT ck_state_state_one_outcome "
        "CHECK (NOT (is_approved AND is_denied))"
    )
    op.execute("ALTER TABLE state DROP CONSTRAINT IF EXISTS ck_state_state_outcome_normal")
    op.execute(
        "ALTER TABLE state ADD CONSTRAINT ck_state_state_outcome_normal "
        "CHECK (kind = 'normal' OR NOT (is_approved OR is_denied))"
    )
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS accepted_state_keys")
    op.execute("ALTER TABLE budget DROP COLUMN IF EXISTS denied_state_keys")


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for col in ("accepted_state_keys", "denied_state_keys"):
        op.execute(
            f"ALTER TABLE budget ADD COLUMN IF NOT EXISTS {col} jsonb NOT NULL DEFAULT '[]'"
        )
    for col, flag in (("accepted_state_keys", "is_approved"), ("denied_state_keys", "is_denied")):
        op.execute(
            f"UPDATE budget SET {col} = COALESCE("
            f"(SELECT jsonb_agg(DISTINCT key ORDER BY key) FROM state WHERE {flag}), '[]') "
            "WHERE parent_id IS NULL"
        )
    op.execute("ALTER TABLE state DROP CONSTRAINT IF EXISTS ck_state_state_outcome_normal")
    op.execute("ALTER TABLE state DROP CONSTRAINT IF EXISTS ck_state_state_one_outcome")
    op.execute("ALTER TABLE state DROP COLUMN IF EXISTS is_denied")
    op.execute("ALTER TABLE state DROP COLUMN IF EXISTS is_approved")
