"""Meeting: kind, place and form. Gremium: repeat quorum and guest ballots. Defaults.

``meeting`` gets ``kind`` (``ordinary``), ``location`` (empty) and ``form``
(``presence``). ``gremium`` gets ``repeat_quorum_percent`` (empty) and
``guests_may_vote``. ``meeting_settings`` gets the values that the form of a new
Gremium starts with.

Guest ballots were a setting of the meeting, and only a Gremium without a quorum had
public meetings. The upgrade keeps that state: a Gremium without a quorum that has a
public meeting with voting guests gets ``guests_may_vote`` on. Every other Gremium
starts with the switch off, and its meetings that are not closed go to the mode
``watch``. A new meeting starts in the mode ``watch``.

Idempotent. A fresh database already has the columns from the ``create_all`` baseline
(0001).

Revision ID: c3f58a1e7d94
Revises: a7c41e9d2b56
Create Date: 2026-11-14 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3f58a1e7d94"
down_revision: str | None = "a7c41e9d2b56"
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
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'ordinary'",
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS location TEXT",
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS form TEXT NOT NULL DEFAULT 'presence'",
    _check(
        "meeting",
        "ck_meeting_meeting_kind",
        "kind IN ('ordinary','extraordinary','repeat','constituent')",
    ),
    _check("meeting", "ck_meeting_meeting_form", "form IN ('presence','hybrid','video')"),
    "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS repeat_quorum_percent INTEGER",
    "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS guests_may_vote BOOLEAN NOT NULL DEFAULT false",
    """
    UPDATE gremium g
       SET guests_may_vote = true
     WHERE g.quorum_percent IS NULL
       AND EXISTS (
           SELECT 1 FROM meeting m
            WHERE m.gremium_id = g.id AND m.public_join AND m.guests_mode = 'vote'
       )
    """,
    """
    UPDATE meeting m
       SET guests_mode = 'watch'
      FROM gremium g
     WHERE g.id = m.gremium_id
       AND m.status <> 'closed'
       AND m.guests_mode = 'vote'
       AND (NOT g.guests_may_vote OR g.quorum_percent IS NOT NULL)
    """,
    "ALTER TABLE meeting ALTER COLUMN guests_mode SET DEFAULT 'watch'",
    "ALTER TABLE meeting_settings "
    "ADD COLUMN IF NOT EXISTS default_quorum_percent INTEGER DEFAULT 40",
    "ALTER TABLE meeting_settings "
    "ADD COLUMN IF NOT EXISTS default_repeat_quorum_percent INTEGER DEFAULT 25",
    "ALTER TABLE meeting_settings "
    "ADD COLUMN IF NOT EXISTS default_guests_may_vote BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE meeting_settings "
    "ADD COLUMN IF NOT EXISTS default_allow_vote_delegation BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE meeting_settings "
    "ADD COLUMN IF NOT EXISTS default_delegation_lead_minutes INTEGER NOT NULL DEFAULT 120",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting_settings DROP COLUMN IF EXISTS default_delegation_lead_minutes",
    "ALTER TABLE meeting_settings DROP COLUMN IF EXISTS default_allow_vote_delegation",
    "ALTER TABLE meeting_settings DROP COLUMN IF EXISTS default_guests_may_vote",
    "ALTER TABLE meeting_settings DROP COLUMN IF EXISTS default_repeat_quorum_percent",
    "ALTER TABLE meeting_settings DROP COLUMN IF EXISTS default_quorum_percent",
    "ALTER TABLE meeting ALTER COLUMN guests_mode SET DEFAULT 'vote'",
    "ALTER TABLE gremium DROP COLUMN IF EXISTS guests_may_vote",
    "ALTER TABLE gremium DROP COLUMN IF EXISTS repeat_quorum_percent",
    "ALTER TABLE meeting DROP CONSTRAINT IF EXISTS ck_meeting_meeting_form",
    "ALTER TABLE meeting DROP CONSTRAINT IF EXISTS ck_meeting_meeting_kind",
    "ALTER TABLE meeting DROP COLUMN IF EXISTS form",
    "ALTER TABLE meeting DROP COLUMN IF EXISTS location",
    "ALTER TABLE meeting DROP COLUMN IF EXISTS kind",
)


def upgrade() -> None:
    """Add the columns and keep the guest ballots where a Gremium uses them."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Drop the columns. The guest mode of the meetings stays as it is."""
    for statement in _DOWNGRADE:
        op.execute(statement)
