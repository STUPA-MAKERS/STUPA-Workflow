"""Baseline: extensions, the full schema through create_all, and raw DDL (T-06, squashed).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-10 00:00:01

Pre-alpha squash (#initialdata): two migrations replace the ~48 incremental revisions
that came before. This file holds the schema baseline. `0002_seed` holds the data. No
installed database is left, because every one of them was reset. A clean restart is
therefore safe. The squash also removes the broken up and down chain that `create_all`
plus later ALTER statements produced (duplicate columns).

Single source: `app.db.Base.metadata` (filled through `app.models`) builds the whole
schema, so the models and the migration always agree. This file adds only what
`create_all` cannot express (security.md §4 / data-model §3):

* Extensions `pgcrypto` (`gen_random_uuid()`) and `citext` (case-insensitive email).
  They run before `create_all`, because column defaults and types need them.
* Audit append-only: the `BEFORE UPDATE/DELETE` (row) and `BEFORE TRUNCATE` (statement)
  triggers run `RAISE EXCEPTION`. A least-privilege grant goes to `audit_writer`.
* Materialized view `mv_status_distribution` (Gremium × state).
  Each view carries a unique index for `REFRESH … CONCURRENTLY` (worker).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401  — fills Base.metadata
from app.db import Base

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_WRITER_ROLE = "audit_writer"

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION audit_entry_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_entry is append-only; % denied', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_GRANT = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_AUDIT_WRITER_ROLE}') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_entry FROM {_AUDIT_WRITER_ROLE};
        GRANT INSERT, SELECT ON TABLE audit_entry TO {_AUDIT_WRITER_ROLE};
    END IF;
END $$;
"""

_MV_STATUS = """
CREATE MATERIALIZED VIEW mv_status_distribution AS
SELECT a.gremium_id       AS gremium_id,
       a.current_state_id AS current_state_id,
       COUNT(*)           AS application_count
FROM application a
GROUP BY a.gremium_id, a.current_state_id
WITH DATA
"""


def upgrade() -> None:
    bind = op.get_bind()
    # The extensions must exist before create_all. Column defaults and types need them.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    # btree_gist gives the uuid equality operator class for the GIST EXCLUDE constraint
    # on `gremium_membership` (`ex_gremium_membership_no_overlap`, #AUD-029).
    # `create_all` emits that constraint inline from the model. On a fresh database
    # the extension MUST therefore exist before create_all. If it does not, CREATE TABLE
    # fails with "data type uuid has no default operator class for gist".
    # (An installed database ran 0001 without the constraint. There 0038 adds it later.)
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    Base.metadata.create_all(bind=bind)

    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_audit_entry_no_update BEFORE UPDATE ON audit_entry "
        "FOR EACH ROW EXECUTE FUNCTION audit_entry_append_only();"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_entry_no_delete BEFORE DELETE ON audit_entry "
        "FOR EACH ROW EXECUTE FUNCTION audit_entry_append_only();"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_entry_no_truncate BEFORE TRUNCATE ON audit_entry "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_entry_append_only();"
    )
    op.execute(_GRANT)

    # `REFRESH … CONCURRENTLY` needs a unique index on each materialized view.
    op.execute(_MV_STATUS)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_status_distribution "
        "ON mv_status_distribution (gremium_id, current_state_id) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Drop the materialized views first, because they depend on the tables. Then drop
    # the schema, then the function and the extensions.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_status_distribution")
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP FUNCTION IF EXISTS audit_entry_append_only()")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
