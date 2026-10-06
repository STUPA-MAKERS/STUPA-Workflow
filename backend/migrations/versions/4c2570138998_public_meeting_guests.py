"""Public meeting with a QR code (#17).

The upgrade:

1. adds three columns to `meeting`: `public_join` (boolean, default false),
   `guests_mode` (`vote` or `watch`, default `vote`, CHECK `ck_meeting_guests_mode`)
   and `join_code` (the short code of the join link). The partial unique index
   `uq_meeting_join_code_open` keeps a code unique among the meetings that are not
   closed.
2. creates the table `meeting_guest`: one row per join request of a person without
   an account. The row holds the display name, the status, the SHA-256 hash of the
   device token, and the decision of the meeting lead (`decided_by` references
   `principal`).
3. adds two nullable columns to `vote`: `present_members` and `present_guests`,
   the attendance that the close of a meeting vote fixes.

All steps are idempotent. A fresh database gets the columns and the table from the
`create_all` baseline (0001), because the models already declare them, so the upgrade
uses `ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS` and
`CREATE INDEX IF NOT EXISTS`, and adds the CHECK only when it is missing.

The downgrade drops the table, the index and the columns. The guest rows are lost:
they are personal data of one meeting and have no use without the feature.

Revision ID: 4c2570138998
Revises: 3858ad137185
Create Date: 2026-10-06 09:54:24.673011
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "4c2570138998"
down_revision: str | None = "3858ad137185"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS public_join boolean NOT NULL DEFAULT false",
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS guests_mode text NOT NULL DEFAULT 'vote'",
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS join_code text",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_meeting_guests_mode'
        ) THEN
            ALTER TABLE meeting ADD CONSTRAINT ck_meeting_guests_mode
                CHECK (guests_mode IN ('vote','watch'));
        END IF;
    END $$
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_meeting_join_code_open ON meeting (join_code) "
        "WHERE join_code IS NOT NULL AND status <> 'closed'"
    ),
    """
    CREATE TABLE IF NOT EXISTS meeting_guest (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        created_at timestamptz DEFAULT now() NOT NULL,
        meeting_id uuid NOT NULL,
        seq integer NOT NULL,
        display_name text,
        status text DEFAULT 'pending' NOT NULL,
        token_hash bytea,
        requested_at timestamptz NOT NULL,
        decided_at timestamptz,
        decided_by uuid,
        admitted_at timestamptz,
        last_seen_at timestamptz,
        CONSTRAINT pk_meeting_guest PRIMARY KEY (id),
        CONSTRAINT fk_meeting_guest_meeting_id_meeting FOREIGN KEY (meeting_id)
            REFERENCES meeting (id) ON DELETE CASCADE,
        CONSTRAINT fk_meeting_guest_decided_by_principal FOREIGN KEY (decided_by)
            REFERENCES principal (id) ON DELETE SET NULL,
        CONSTRAINT ck_meeting_guest_status
            CHECK (status IN ('pending','admitted','rejected','removed','left'))
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS ix_meeting_guest_meeting_status "
        "ON meeting_guest (meeting_id, status)"
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_meeting_guest_token_hash "
        "ON meeting_guest (token_hash) WHERE token_hash IS NOT NULL"
    ),
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS present_members integer",
    "ALTER TABLE vote ADD COLUMN IF NOT EXISTS present_guests integer",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE vote DROP COLUMN IF EXISTS present_guests",
    "ALTER TABLE vote DROP COLUMN IF EXISTS present_members",
    "DROP TABLE IF EXISTS meeting_guest",
    "DROP INDEX IF EXISTS uq_meeting_join_code_open",
    "ALTER TABLE meeting DROP CONSTRAINT IF EXISTS ck_meeting_guests_mode",
    "ALTER TABLE meeting DROP COLUMN IF EXISTS join_code",
    "ALTER TABLE meeting DROP COLUMN IF EXISTS guests_mode",
    "ALTER TABLE meeting DROP COLUMN IF EXISTS public_join",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
