"""Exactly one flow and no versions: move every application to the one global flow.

The migration forces the invariant that the product owner requires:
* Exactly one `flow_version` stays: the active or newest global flow. The migration
  deletes the rest: old global versions and per-type flows.
* The migration pins every application to this flow. It maps `current_state` by KEY. A
  state that no longer exists maps to the initial state.
* The remaining flow keeps at least one initial state. If it has none, the first state
  becomes the initial state.

Idempotent: only one flow is left after the run, so a second run is a no-op.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_single_global_flow"
down_revision: str | None = "0005_accounts_and_transfers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FORCE = """
DO $$
DECLARE
    gid uuid;
    init_id uuid;
    has_type_col boolean;
BEGIN
    -- New installations (baseline = create_all from the CURRENT models) do not know
    -- the type-flow columns any more since 0019. Run each column-dependent step only
    -- if the column (existing database) is still there.
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'flow_version' AND column_name = 'application_type_id'
    ) INTO has_type_col;

    -- Select the one global flow (active first, else the highest version).
    IF has_type_col THEN
        SELECT id INTO gid FROM flow_version
         WHERE application_type_id IS NULL
         ORDER BY active DESC, version DESC
         LIMIT 1;
    ELSE
        SELECT id INTO gid FROM flow_version
         ORDER BY active DESC, version DESC
         LIMIT 1;
    END IF;
    IF gid IS NULL THEN
        -- No global flow: make one of the available flows the global flow.
        SELECT id INTO gid FROM flow_version ORDER BY version DESC LIMIT 1;
    END IF;
    IF gid IS NULL THEN
        RETURN;  -- no flow at all → nothing to force.
    END IF;

    IF has_type_col THEN
        UPDATE flow_version SET application_type_id = NULL, active = true WHERE id = gid;
    ELSE
        UPDATE flow_version SET active = true WHERE id = gid;
    END IF;

    -- At least one initial state.
    SELECT id INTO init_id FROM state
     WHERE flow_version_id = gid AND is_initial LIMIT 1;
    IF init_id IS NULL THEN
        SELECT id INTO init_id FROM state
         WHERE flow_version_id = gid ORDER BY key LIMIT 1;
        IF init_id IS NOT NULL THEN
            UPDATE state SET is_initial = true WHERE id = init_id;
        END IF;
    END IF;

    -- Move each application to the one flow. Map the state by KEY, else use the initial state.
    UPDATE application a
       SET current_state_id = COALESCE(
               (SELECT s2.id FROM state s2
                 WHERE s2.flow_version_id = gid
                   AND s2.key = (SELECT s1.key FROM state s1
                                  WHERE s1.id = a.current_state_id)),
               init_id),
           flow_version_id = gid;

    -- Detach the per-type pointers, so that the migration can delete their versions
    -- (the column stays only on existing databases, it drops with 0019).
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'application_type'
           AND column_name = 'active_flow_version_id'
    ) THEN
        UPDATE application_type SET active_flow_version_id = NULL;
    END IF;

    -- Delete all other flows (state/transition rows go with them through CASCADE).
    DELETE FROM flow_version WHERE id <> gid;
END $$;
"""


def upgrade() -> None:
    op.execute(_FORCE)


def downgrade() -> None:
    # Not reversible, because the deleted old versions are gone. This no-op is on purpose.
    pass
