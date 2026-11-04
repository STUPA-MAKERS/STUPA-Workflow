"""fix_vote_status_constraint: one vote status CHECK that allows ``cancelled``.

Migration 0001 (``create_all``) created the CHECK under the naming convention as
``ck_vote_vote_status``, with the value range of that time (``draft``, ``open``,
``closed``). Migration 0012 tried to widen it with ``DROP CONSTRAINT IF EXISTS
vote_status``. That statement missed the constraint with the convention name and added
a second one named ``vote_status``. On a database built this way, the old
``ck_vote_vote_status`` survives without ``cancelled``, so every cancel of a vote
fails with a CheckViolation (500): the manual cancel, the cancel when an application
leaves its vote state, and the cancel of the drafts when a meeting closes.

A fresh database does not show the fault, because ``create_all`` builds
``ck_vote_vote_status`` from the current model, which already allows ``cancelled``.

The upgrade drops both names and creates ONE constraint under the convention name with
the full value range. A fresh schema and a migrated schema then carry the same name and
the same condition. The statements are idempotent.

Revision ID: 4fd514277924
Revises: b80a146809d4
Create Date: 2026-11-04 14:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "4fd514277924"
down_revision: str | None = "b80a146809d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "CHECK (status IN ('draft','open','closed','cancelled'))"

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS vote_status",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_status",
    f"ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_status {_STATUSES}",
)

#: The downgrade keeps the full value range, because cancelled rows exist by then. It
#: adds the 0012 name beside the convention name, which is the state of a fresh database
#: before this revision.
_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS vote_status",
    f"ALTER TABLE vote ADD CONSTRAINT vote_status {_STATUSES}",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
