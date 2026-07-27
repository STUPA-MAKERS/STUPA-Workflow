"""Protocol: the `rendering` status (async protocol render, T-22 follow-up).

`finalize` no longer blocks the request. The protocol moves to `rendering`. An
arq worker then renders the PDF, sends the mail and sets `final`. After a
permanent failure the protocol falls back to `draft`. The `protocol_status`
check constraint must allow the new intermediate status. The migration is
idempotent. It drops the constraint if it exists and creates it again.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_protocol_rendering_status"
down_revision: str | None = "0010_application_email_confirmed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT protocol_status "
        "CHECK (status IN ('draft','rendering','final'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # Reset a render in progress to draft. Otherwise the row breaks the
    # restored, narrower constraint.
    "UPDATE protocol SET status = 'draft' WHERE status = 'rendering'",
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT protocol_status "
        "CHECK (status IN ('draft','final'))"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
