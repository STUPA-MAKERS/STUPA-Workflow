"""Remove the rest of the per-type flow (#28 closure): only the global flow stays.

Migration 0006 forced the cutover to one global `flow_version` row and deleted
the old versions. The columns and constraints of the per-type model stayed in
the schema. This migration drops them:

* `application_type.active_flow_version_id`
* `flow_version.application_type_id` (dependent indexes and constraints drop
  with the column).

It then adds a unique `version` and a partial unique index on `active` that
allows exactly ONE active flow. The migration prepares the existing data first.
It deactivates duplicate active rows and renumbers duplicate version numbers.
The migration is idempotent (`IF [NOT] EXISTS`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_drop_type_flows"
down_revision: str | None = "0018_notification_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEDUPE = """
DO $$
DECLARE
    keep uuid;
    has_type_col boolean;
BEGIN
    -- Existing databases can hold more than one active row (per-type active rows
    -- from the time before the 0006 cutover, or from an older 0006 variant). Before
    -- the partial unique index, only ONE active row can stay. Keep the global row
    -- (application_type_id IS NULL) first, else keep the highest version.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'flow_version' AND column_name = 'application_type_id'
    ) INTO has_type_col;

    IF has_type_col THEN
        SELECT id INTO keep FROM flow_version
         WHERE active
         ORDER BY (application_type_id IS NULL) DESC, version DESC, created_at DESC
         LIMIT 1;
    ELSE
        SELECT id INTO keep FROM flow_version
         WHERE active
         ORDER BY version DESC, created_at DESC
         LIMIT 1;
    END IF;

    IF keep IS NOT NULL THEN
        UPDATE flow_version SET active = false WHERE active AND id <> keep;
    END IF;
END $$;
"""

# The unique constraint on `version` needs distinct version numbers. Per-type
# flows could give the same number to several rows. The renumber step works in a
# deterministic order: old number first, then age. It does nothing when there
# are no duplicates. It runs AFTER the column and constraint drops, so that no
# old unique constraint breaks in between.
_RENUMBER = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM flow_version GROUP BY version HAVING count(*) > 1
    ) THEN
        UPDATE flow_version f
           SET version = r.rn
          FROM (
              SELECT id, row_number() OVER (ORDER BY version, created_at, id) AS rn
                FROM flow_version
          ) r
         WHERE f.id = r.id AND f.version <> r.rn;
    END IF;
END $$;
"""

_UPGRADE: tuple[str, ...] = (
    _DEDUPE,
    "ALTER TABLE application_type DROP COLUMN IF EXISTS active_flow_version_id",
    # The dependent indexes and unique constraints drop with the column. This
    # covers the one_active_per_type index and the unique on (type, version).
    "ALTER TABLE flow_version DROP COLUMN IF EXISTS application_type_id",
    "DROP INDEX IF EXISTS uq_flow_version_one_active_global",
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_version_one_active_global "
        "ON flow_version (active) WHERE active"
    ),
    # Drop both possible names, then create the canonical one again. An old
    # database carries the Postgres default name. A fresh database carries the
    # name from the naming convention of the models.
    "ALTER TABLE flow_version DROP CONSTRAINT IF EXISTS flow_version_version_key",
    "ALTER TABLE flow_version DROP CONSTRAINT IF EXISTS uq_flow_version_version",
    _RENUMBER,
    (
        "ALTER TABLE flow_version "
        "ADD CONSTRAINT uq_flow_version_version UNIQUE (version)"
    ),
)

def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    # Not reversible, the same as 0006. The 0006 cutover deleted the per-type
    # flow data. A restore of the columns would bring back dead structures only.
    # It would also break the drop_all downgrade of the baseline. The current
    # models no longer know the foreign key to application_type. This downgrade
    # does nothing on purpose.
    pass
