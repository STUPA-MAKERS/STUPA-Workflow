"""Votes: the Umlaufverfahren and the election result `no_majority`.

The upgrade changes the table `vote`:

1. The kind CHECK `ck_vote_vote_kind` also allows `circular` (the Umlaufverfahren).
2. The result CHECK `ck_vote_vote_result` also allows `no_majority` (an election for
   one seat in which nobody reached the majority of the members).
3. `cancel_reason` (text, nullable): `objection` for an Umlaufverfahren that a member
   objected to.

`meeting_settings` gets `circular_min_days` (3): the least number of days of the cast
window of an Umlaufverfahren.

Idempotent. A fresh database already has all of this from the ``create_all`` baseline
(0001).

Revision ID: a47c0e93b1d6
Revises: d81b6e42a9f3
Create Date: 2026-11-14 21:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a47c0e93b1d6"
down_revision: str | None = "d81b6e42a9f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS cancel_reason text",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_kind",
    (
        "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_kind "
        "CHECK (kind IN ('motion','election','poll','circular'))"
    ),
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_result",
    (
        "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_result CHECK (result IS NULL OR "
        "result IN ('passed','rejected','tie','elected','runoff','no_majority'))"
    ),
    "ALTER TABLE meeting_settings "
    "ADD COLUMN IF NOT EXISTS circular_min_days INTEGER NOT NULL DEFAULT 3",
)

#: The circular rows go first, because the narrower CHECK cannot hold them. An election
#: without a majority reads `rejected` again.
_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting_settings DROP COLUMN IF EXISTS circular_min_days",
    "DELETE FROM protocol_vote_ref WHERE vote_id IN (SELECT id FROM vote WHERE kind = 'circular')",
    "DELETE FROM vote WHERE kind = 'circular'",
    "UPDATE vote SET result = 'rejected' WHERE result = 'no_majority'",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_result",
    (
        "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_result CHECK (result IS NULL OR "
        "result IN ('passed','rejected','tie','elected','runoff'))"
    ),
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS ck_vote_vote_kind",
    (
        "ALTER TABLE vote ADD CONSTRAINT ck_vote_vote_kind "
        "CHECK (kind IN ('motion','election','poll'))"
    ),
    "ALTER TABLE vote DROP COLUMN IF EXISTS cancel_reason",
)


def upgrade() -> None:
    """Widen both checks and add the two columns."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the circular votes and narrow both checks again."""
    for statement in _DOWNGRADE:
        op.execute(statement)
