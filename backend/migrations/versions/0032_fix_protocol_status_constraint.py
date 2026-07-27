"""Normalize the protocol status CHECK (fix: `rendering` gets rejected).

Bug: migration 0001 (`create_all`) created the CHECK under the naming
convention as `ck_protocol_protocol_status`, with the value range of that time
(`draft` and `final`). Migration 0011 tried to replace it with `DROP CONSTRAINT
IF EXISTS protocol_status`. That statement missed the constraint with the
convention name and added a second one named `protocol_status`. On a database
built this way, the old `ck_protocol_protocol_status` CHECK survives without
`rendering`. `finalize` then sets the status to `rendering` and throws a 500
(CheckViolation).

Fix: drop both possible constraint names and create ONE constraint under the
convention name `ck_protocol_protocol_status` with the full value range. A
fresh schema from `create_all` and the migrations then carry the same name and
the same condition. The statements are idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_fix_protocol_status_ck"
down_revision: str | None = "0031_non_public_tops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS protocol_status",
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS ck_protocol_protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT ck_protocol_protocol_status "
        "CHECK (status IN ('draft','rendering','final'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # Symmetric: keep the constraint, but put it back under the 0011 name.
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS ck_protocol_protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT protocol_status "
        "CHECK (status IN ('draft','rendering','final'))"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
