"""Vote: the `cancelled` status (cancel a vote by a manual transition, #abort-vote).

An application can leave its `vote` state through a **manual** transition, for
example "cancel vote". The platform then cancels the open votes of that
application. Without this status the votes stay open forever, because `close`
finds no branch and fails with 409. The `vote_status` check constraint must
allow the new end status. The migration is idempotent. It drops the constraint
if it exists and creates it again.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_vote_cancelled_status"
down_revision: str | None = "0011_protocol_rendering_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS vote_status",
    (
        "ALTER TABLE vote ADD CONSTRAINT vote_status "
        "CHECK (status IN ('draft','open','closed','cancelled'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # Treat a cancelled vote as closed with no result. Otherwise the row breaks
    # the restored, narrower constraint.
    "UPDATE vote SET status = 'closed' WHERE status = 'cancelled'",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS vote_status",
    (
        "ALTER TABLE vote ADD CONSTRAINT vote_status "
        "CHECK (status IN ('draft','open','closed'))"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
