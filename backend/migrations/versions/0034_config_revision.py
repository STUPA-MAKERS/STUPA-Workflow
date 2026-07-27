"""config_revision: append-only config snapshot chain and the `audit.revert` permission.

#config-versioning. The table holds a universal, **append-only** history of the
versioned configs (forms, flow, branding). A database trigger rejects UPDATE, DELETE
and TRUNCATE, so a version is **never** deletable. The table also gets a
least-privilege grant to `audit_writer`, the same as `audit_entry`. The destructive
permission `audit.revert` covers the audit-log revert. The migration seeds it to the
`admin` role.

All statements are idempotent (`IF NOT EXISTS` or `ON CONFLICT DO NOTHING`). The
downgrade is a clean round trip.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0034_config_revision"
down_revision: str | None = "0033_tz_aware_status_version_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_WRITER_ROLE = "audit_writer"

_TABLE = """
CREATE TABLE IF NOT EXISTS config_revision (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    version integer NOT NULL,
    snapshot jsonb NOT NULL DEFAULT '{}',
    prev_revision_id uuid REFERENCES config_revision (id) ON DELETE RESTRICT,
    created_by text,
    at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_config_revision_entity_version
        UNIQUE (entity_type, entity_id, version)
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_config_revision_entity "
    "ON config_revision (entity_type, entity_id, version)"
)

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION config_revision_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'config_revision is append-only; % denied', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_GRANT = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_AUDIT_WRITER_ROLE}') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE config_revision FROM {_AUDIT_WRITER_ROLE};
        GRANT INSERT, SELECT ON TABLE config_revision TO {_AUDIT_WRITER_ROLE};
    END IF;
END $$;
"""

_SEED_PERM = (
    "INSERT INTO role_permission (role_id, permission) "
    "SELECT r.id, 'audit.revert' FROM role r WHERE r.key = 'admin' "
    "ON CONFLICT DO NOTHING"
)


def upgrade() -> None:
    op.execute(_TABLE)
    op.execute(_INDEX)
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_config_revision_no_update BEFORE UPDATE ON config_revision "
        "FOR EACH ROW EXECUTE FUNCTION config_revision_append_only();"
    )
    op.execute(
        "CREATE TRIGGER trg_config_revision_no_delete BEFORE DELETE ON config_revision "
        "FOR EACH ROW EXECUTE FUNCTION config_revision_append_only();"
    )
    op.execute(
        "CREATE TRIGGER trg_config_revision_no_truncate BEFORE TRUNCATE ON config_revision "
        "FOR EACH STATEMENT EXECUTE FUNCTION config_revision_append_only();"
    )
    op.execute(_GRANT)
    op.execute(_SEED_PERM)


def downgrade() -> None:
    op.execute("DELETE FROM role_permission WHERE permission = 'audit.revert'")
    op.execute("DROP TRIGGER IF EXISTS trg_config_revision_no_truncate ON config_revision")
    op.execute("DROP TRIGGER IF EXISTS trg_config_revision_no_delete ON config_revision")
    op.execute("DROP TRIGGER IF EXISTS trg_config_revision_no_update ON config_revision")
    op.execute("DROP TABLE IF EXISTS config_revision")
    op.execute("DROP FUNCTION IF EXISTS config_revision_append_only()")
