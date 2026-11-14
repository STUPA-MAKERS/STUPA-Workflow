"""Gremium: limit of delegations per delegate and delegations in elections.

``gremium`` gets ``delegation_max_per_delegate`` (2) and ``delegation_in_elections``
(off). ``meeting_settings`` gets the limit that the form of a new Gremium starts with.

A delegate can hold more than one voting delegation now, up to the limit of the
Gremium, so the unique index on (meeting, delegate) of the voting delegations goes
away. The downgrade does not bring it back, because rows can break it by then.

Idempotent. A fresh database already has the columns from the ``create_all`` baseline
(0001).

Revision ID: d81b6e42a9f3
Revises: c3f58a1e7d94
Create Date: 2026-11-14 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d81b6e42a9f3"
down_revision: str | None = "c3f58a1e7d94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(table: str, name: str, rule: str) -> str:
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = '{table}'::regclass AND conname = '{name}'
        ) THEN
            ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({rule});
        END IF;
    END $$
    """


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE gremium "
    "ADD COLUMN IF NOT EXISTS delegation_max_per_delegate INTEGER NOT NULL DEFAULT 2",
    "ALTER TABLE gremium "
    "ADD COLUMN IF NOT EXISTS delegation_in_elections BOOLEAN NOT NULL DEFAULT false",
    _check(
        "gremium",
        "ck_gremium_delegation_max_per_delegate",
        "delegation_max_per_delegate BETWEEN 1 AND 20",
    ),
    "ALTER TABLE meeting_settings "
    "ADD COLUMN IF NOT EXISTS default_delegation_max_per_delegate INTEGER NOT NULL DEFAULT 2",
    "DROP INDEX IF EXISTS uq_meeting_delegation_voting_delegate",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting_settings DROP COLUMN IF EXISTS default_delegation_max_per_delegate",
    "ALTER TABLE gremium DROP CONSTRAINT IF EXISTS ck_gremium_delegation_max_per_delegate",
    "ALTER TABLE gremium DROP COLUMN IF EXISTS delegation_in_elections",
    "ALTER TABLE gremium DROP COLUMN IF EXISTS delegation_max_per_delegate",
)


def upgrade() -> None:
    """Add the settings and drop the one-voting-delegation index."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the settings. The index stays away."""
    for statement in _DOWNGRADE:
        op.execute(statement)
