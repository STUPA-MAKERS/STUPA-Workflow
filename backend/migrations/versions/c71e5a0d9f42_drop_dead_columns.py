"""drop_dead_columns: remove tables and columns that no code reads or writes.

The upgrade:

1. Drops ``ballot``. Every vote is secret, so no code writes an open ballot. The
   upgrade stops when the table still holds a row, because a row is a cast vote.
2. Reduces ``role_assignment`` to ``(id, principal_id, role_id, granted_by)``. Only the
   bootstrap writes rows. It first deletes the rows that the dropped columns made
   ineffective or temporary (an end, a start in the future, a self-delegation), because
   without the columns such a row would grant its role for ever.
3. Drops the term of ``gremium_membership``. ``membership_sync`` writes every row with an
   open term. It first deletes the rows whose term does not hold now. The EXCLUDE
   constraint then becomes ``UNIQUE (principal_id, gremium_id)``.
4. Drops ``magic_link.scope``, ``magic_link.single_use`` and ``applicant_session.scope``.
   A new link is always an edit link that can be used more than once. It first deletes
   the old view and single-use links and the view sessions.
5. Drops ``webhook_delivery.next_at``: the retry runs as a deferred arq job.
6. Drops the actor stamps that nothing shows: ``application.archived_by``,
   ``fiscal_year.closed_by``, ``meeting_agenda_item.done_by`` and
   ``protocol_keeper_period.handed_over_by``. The audit log keeps each actor.
7. Moves ``mail_list`` into ``gremium.protocol_recipients``, in the order of the first
   occurrence, and drops the table.
8. Makes ``attachment.draft_token_hash`` a foreign key to ``attachment_draft_token``
   and drops the copy ``attachment.draft_expires_at``. A draft hash without a token row
   gets one with the latest end of its drafts.
9. Drops ``cd_variant.base_variant``: no render path reads it.

Migration 0001 builds a fresh schema from the current models, so every statement is
idempotent and every reference to a dropped object checks that it exists.

**The data changes are one-way.** The downgrade restores the schema with empty or
default columns and rebuilds ``mail_list`` from ``gremium.protocol_recipients``. It does
not restore the deleted rows or the dropped values.

Revision ID: c71e5a0d9f42
Revises: b6f901a77cb7
Create Date: 2026-11-05 23:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c71e5a0d9f42"
down_revision: str | None = "b6f901a77cb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> str:
    return (
        "EXISTS (SELECT 1 FROM information_schema.columns "
        f"WHERE table_schema = current_schema() AND table_name = '{table}' "
        f"AND column_name = '{column}')"
    )


_UPGRADE: tuple[str, ...] = (
    # 1. ballot
    """
    DO $$
    DECLARE
        has_rows boolean := false;
    BEGIN
        IF to_regclass('ballot') IS NOT NULL THEN
            EXECUTE 'SELECT EXISTS (SELECT 1 FROM ballot)' INTO has_rows;
        END IF;
        IF has_rows THEN
            RAISE EXCEPTION 'ballot still holds rows: convert them to secret ballots first';
        END IF;
    END $$
    """,
    "DROP TABLE IF EXISTS ballot",
    # 2. role_assignment
    f"""
    DO $$
    BEGIN
        IF {_has_column("role_assignment", "valid_until")} THEN
            DELETE FROM role_assignment
             WHERE valid_until IS NOT NULL
                OR valid_from > now()
                OR delegated_by IS NOT NULL;
        END IF;
    END $$
    """,
    "DROP INDEX IF EXISTS ix_role_assignment_delegated_by",
    "ALTER TABLE role_assignment DROP CONSTRAINT IF EXISTS fk_role_assignment_gremium_id_gremium",
    "ALTER TABLE role_assignment DROP COLUMN IF EXISTS gremium_id",
    "ALTER TABLE role_assignment DROP COLUMN IF EXISTS delegated_by",
    "ALTER TABLE role_assignment DROP COLUMN IF EXISTS valid_from",
    "ALTER TABLE role_assignment DROP COLUMN IF EXISTS valid_until",
    "ALTER TABLE role_assignment DROP COLUMN IF EXISTS delegate_voting",
    # 3. gremium_membership
    f"""
    DO $$
    BEGIN
        IF {_has_column("gremium_membership", "valid_until")} THEN
            DELETE FROM gremium_membership
             WHERE (valid_until IS NOT NULL AND valid_until <= now())
                OR (valid_from IS NOT NULL AND valid_from > now());
        END IF;
    END $$
    """,
    "ALTER TABLE gremium_membership DROP CONSTRAINT IF EXISTS ex_gremium_membership_no_overlap",
    "ALTER TABLE gremium_membership DROP COLUMN IF EXISTS valid_from",
    "ALTER TABLE gremium_membership DROP COLUMN IF EXISTS valid_until",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'gremium_membership'::regclass
               AND conname = 'uq_gremium_membership_principal_gremium'
        ) THEN
            ALTER TABLE gremium_membership ADD CONSTRAINT uq_gremium_membership_principal_gremium
                UNIQUE (principal_id, gremium_id);
        END IF;
    END $$
    """,
    # 4. magic_link and applicant_session
    f"""
    DO $$
    BEGIN
        IF {_has_column("magic_link", "scope")} THEN
            DELETE FROM magic_link WHERE scope <> 'edit' OR single_use;
        END IF;
        IF {_has_column("applicant_session", "scope")} THEN
            DELETE FROM applicant_session WHERE scope <> 'edit';
        END IF;
    END $$
    """,
    "ALTER TABLE magic_link DROP CONSTRAINT IF EXISTS ck_magic_link_magic_link_scope",
    "ALTER TABLE magic_link DROP CONSTRAINT IF EXISTS ck_magic_link_magic_link_unlimited_edit_only",
    "ALTER TABLE magic_link DROP COLUMN IF EXISTS scope",
    "ALTER TABLE magic_link DROP COLUMN IF EXISTS single_use",
    "ALTER TABLE applicant_session DROP COLUMN IF EXISTS scope",
    # 5. webhook_delivery
    "DROP INDEX IF EXISTS ix_webhook_delivery_status_next_at",
    "ALTER TABLE webhook_delivery DROP COLUMN IF EXISTS next_at",
    # 6. actor stamps
    "ALTER TABLE application DROP COLUMN IF EXISTS archived_by",
    "ALTER TABLE fiscal_year DROP COLUMN IF EXISTS closed_by",
    "ALTER TABLE meeting_agenda_item DROP COLUMN IF EXISTS done_by",
    "ALTER TABLE protocol_keeper_period DROP COLUMN IF EXISTS handed_over_by",
    # 7. mail_list -> gremium.protocol_recipients
    "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS protocol_recipients text[] NOT NULL DEFAULT '{}'",
    """
    DO $$
    BEGIN
        IF to_regclass('mail_list') IS NOT NULL THEN
            UPDATE gremium g
               SET protocol_recipients = sub.recipients
              FROM (
                SELECT gremium_id, array_agg(addr ORDER BY first_seen) AS recipients
                  FROM (
                    SELECT m.gremium_id, r.addr, min(r.pos) AS first_seen
                      FROM mail_list m
                     CROSS JOIN LATERAL unnest(m.recipients) WITH ORDINALITY AS r(addr, pos)
                     WHERE m.active
                     GROUP BY m.gremium_id, r.addr
                  ) addrs
                 GROUP BY gremium_id
              ) sub
             WHERE g.id = sub.gremium_id;
        END IF;
    END $$
    """,
    "DROP TABLE IF EXISTS mail_list",
    # 8. attachment draft token
    f"""
    DO $$
    BEGIN
        IF {_has_column("attachment", "draft_expires_at")} THEN
            INSERT INTO attachment_draft_token (token_hash, expires_at)
            SELECT draft_token_hash, max(COALESCE(draft_expires_at, now()))
              FROM attachment
             WHERE draft_token_hash IS NOT NULL
             GROUP BY draft_token_hash
            ON CONFLICT (token_hash) DO UPDATE
               SET expires_at = GREATEST(attachment_draft_token.expires_at, EXCLUDED.expires_at);
        END IF;
    END $$
    """,
    "ALTER TABLE attachment DROP CONSTRAINT IF EXISTS ck_attachment_draft_columns_paired",
    "DROP INDEX IF EXISTS ix_attachment_draft_expires_at",
    "ALTER TABLE attachment DROP COLUMN IF EXISTS draft_expires_at",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = 'attachment'::regclass
               AND conname = 'fk_attachment_draft_token_hash_attachment_draft_token'
        ) THEN
            ALTER TABLE attachment
                ADD CONSTRAINT fk_attachment_draft_token_hash_attachment_draft_token
                FOREIGN KEY (draft_token_hash) REFERENCES attachment_draft_token (token_hash)
                ON DELETE CASCADE;
        END IF;
    END $$
    """,
    # 9. cd_variant.base_variant
    "ALTER TABLE cd_variant DROP CONSTRAINT IF EXISTS ck_cd_variant_base_variant",
    "ALTER TABLE cd_variant DROP COLUMN IF EXISTS base_variant",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE cd_variant ADD COLUMN IF NOT EXISTS base_variant text NOT NULL DEFAULT 'report'",
    "ALTER TABLE cd_variant ADD CONSTRAINT ck_cd_variant_base_variant "
    "CHECK (base_variant IN ('report','protocol'))",
    "ALTER TABLE attachment DROP CONSTRAINT IF EXISTS "
    "fk_attachment_draft_token_hash_attachment_draft_token",
    "ALTER TABLE attachment ADD COLUMN IF NOT EXISTS draft_expires_at timestamptz",
    "UPDATE attachment a SET draft_expires_at = t.expires_at "
    "FROM attachment_draft_token t WHERE a.draft_token_hash = t.token_hash",
    "ALTER TABLE attachment ADD CONSTRAINT ck_attachment_draft_columns_paired "
    "CHECK ((draft_token_hash IS NULL) = (draft_expires_at IS NULL))",
    "CREATE INDEX IF NOT EXISTS ix_attachment_draft_expires_at ON attachment (draft_expires_at)",
    """
    CREATE TABLE IF NOT EXISTS mail_list (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        gremium_id uuid NOT NULL,
        name text NOT NULL,
        recipients text[] DEFAULT '{}' NOT NULL,
        active boolean DEFAULT true NOT NULL,
        CONSTRAINT pk_mail_list PRIMARY KEY (id),
        CONSTRAINT fk_mail_list_gremium_id_gremium FOREIGN KEY (gremium_id)
            REFERENCES gremium (id) ON DELETE CASCADE
    )
    """,
    "INSERT INTO mail_list (gremium_id, name, recipients, active) "
    "SELECT id, 'protocol', protocol_recipients, true FROM gremium "
    "WHERE cardinality(protocol_recipients) > 0",
    "ALTER TABLE gremium DROP COLUMN IF EXISTS protocol_recipients",
    "ALTER TABLE protocol_keeper_period ADD COLUMN IF NOT EXISTS handed_over_by text "
    "NOT NULL DEFAULT 'system:migration'",
    "ALTER TABLE meeting_agenda_item ADD COLUMN IF NOT EXISTS done_by text",
    "ALTER TABLE fiscal_year ADD COLUMN IF NOT EXISTS closed_by text",
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS archived_by text",
    "ALTER TABLE webhook_delivery ADD COLUMN IF NOT EXISTS next_at timestamptz",
    "CREATE INDEX IF NOT EXISTS ix_webhook_delivery_status_next_at "
    "ON webhook_delivery (status, next_at)",
    "ALTER TABLE applicant_session ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'edit'",
    "ALTER TABLE magic_link ADD COLUMN IF NOT EXISTS single_use boolean NOT NULL DEFAULT false",
    "ALTER TABLE magic_link ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'edit'",
    "ALTER TABLE magic_link ADD CONSTRAINT ck_magic_link_magic_link_scope "
    "CHECK (scope IN ('edit','view'))",
    "ALTER TABLE magic_link ADD CONSTRAINT ck_magic_link_magic_link_unlimited_edit_only "
    "CHECK (expires_at IS NOT NULL OR scope = 'edit')",
    "ALTER TABLE gremium_membership DROP CONSTRAINT IF EXISTS "
    "uq_gremium_membership_principal_gremium",
    "ALTER TABLE gremium_membership ADD COLUMN IF NOT EXISTS valid_from timestamptz",
    "ALTER TABLE gremium_membership ADD COLUMN IF NOT EXISTS valid_until timestamptz",
    "ALTER TABLE gremium_membership ADD CONSTRAINT ex_gremium_membership_no_overlap "
    "EXCLUDE USING gist (principal_id WITH =, gremium_id WITH =, "
    "tstzrange(coalesce(valid_from, '-infinity'), coalesce(valid_until, 'infinity'), '[)') "
    "WITH &&)",
    "ALTER TABLE role_assignment ADD COLUMN IF NOT EXISTS gremium_id uuid",
    "ALTER TABLE role_assignment ADD CONSTRAINT fk_role_assignment_gremium_id_gremium "
    "FOREIGN KEY (gremium_id) REFERENCES gremium (id) ON DELETE CASCADE",
    "ALTER TABLE role_assignment ADD COLUMN IF NOT EXISTS delegated_by text",
    "ALTER TABLE role_assignment ADD COLUMN IF NOT EXISTS valid_from timestamptz",
    "ALTER TABLE role_assignment ADD COLUMN IF NOT EXISTS valid_until timestamptz",
    "ALTER TABLE role_assignment ADD COLUMN IF NOT EXISTS delegate_voting boolean "
    "NOT NULL DEFAULT false",
    "CREATE INDEX IF NOT EXISTS ix_role_assignment_delegated_by ON role_assignment (delegated_by)",
    """
    CREATE TABLE IF NOT EXISTS ballot (
        id uuid DEFAULT gen_random_uuid() NOT NULL,
        vote_id uuid NOT NULL,
        voter_sub text NOT NULL,
        choice text,
        at timestamptz DEFAULT now() NOT NULL,
        CONSTRAINT pk_ballot PRIMARY KEY (id),
        CONSTRAINT uq_ballot_vote_voter UNIQUE (vote_id, voter_sub),
        CONSTRAINT fk_ballot_vote_id_vote FOREIGN KEY (vote_id)
            REFERENCES vote (id) ON DELETE CASCADE
    )
    """,
)


def upgrade() -> None:
    """Drop the dead tables and columns, after the data steps that they need."""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """Restore the schema with empty columns. The deleted data does not come back."""
    for statement in _DOWNGRADE:
        op.execute(statement)
