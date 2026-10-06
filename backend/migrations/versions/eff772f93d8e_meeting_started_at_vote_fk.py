"""Add `meeting.started_at`, keep the votes of a deleted agenda item (Z7, O9, F21).

The upgrade:

1. adds `meeting.started_at`, the real start of a meeting. The transition from
   `planned` to `live` sets it once. This is idempotent: a fresh database already
   gets the column from the `create_all` baseline (0001), and a migrated database
   gets it through `ADD COLUMN IF NOT EXISTS`. There is no backfill. The audit log
   holds no meeting start (meetings were not audited before F12), and an invented
   value would show up in a protocol that is rendered again. The migration logs the
   number of live and closed meetings that stay NULL. A reader falls back to the
   planned start.
2. changes the foreign key `vote.agenda_item_id` to `ON DELETE SET NULL` (F21). Before,
   a meeting delete cascaded through the agenda items to the votes, their ballots and
   their protocol references, although `vote.meeting_id` is `SET NULL`. The migration
   drops every foreign key on that column, whatever its name, and creates it again
   under the name of the metadata naming convention. So the baseline and this
   revision agree on one constraint.

The downgrade drops the column and restores `ON DELETE CASCADE`.

Revision ID: eff772f93d8e
Revises: 863a6833fea5
Create Date: 2026-10-01 12:49:20.436942
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eff772f93d8e"
down_revision: str | None = "863a6833fea5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_FK = "fk_vote_agenda_item_id_meeting_agenda_item"


def _replace_agenda_item_fk(on_delete: str) -> None:
    """Drop every foreign key on `vote.agenda_item_id` and create it with `on_delete`."""
    op.execute(
        """
        DO $$
        DECLARE c record;
        BEGIN
            FOR c IN
                SELECT con.conname
                  FROM pg_constraint AS con
                  JOIN pg_attribute AS att
                    ON att.attrelid = con.conrelid
                   AND att.attnum = ANY (con.conkey)
                 WHERE con.conrelid = 'vote'::regclass
                   AND con.contype = 'f'
                   AND att.attname = 'agenda_item_id'
            LOOP
                EXECUTE format('ALTER TABLE vote DROP CONSTRAINT %I', c.conname);
            END LOOP;
        END $$
        """
    )
    op.execute(
        f"ALTER TABLE vote ADD CONSTRAINT {_FK} FOREIGN KEY (agenda_item_id) "
        f"REFERENCES meeting_agenda_item (id) ON DELETE {on_delete}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TABLE meeting ADD COLUMN IF NOT EXISTS started_at timestamptz")
    left = bind.execute(
        sa.text(
            "SELECT count(*) FROM meeting "
            "WHERE status IN ('live', 'closed') AND started_at IS NULL"
        )
    ).scalar_one()
    logger.info(
        "meeting.started_at: %d live or closed meeting(s) without a known start "
        "stay NULL; they show the planned start",
        left,
    )
    _replace_agenda_item_fk("SET NULL")


def downgrade() -> None:
    _replace_agenda_item_fk("CASCADE")
    op.execute("ALTER TABLE meeting DROP COLUMN IF EXISTS started_at")
