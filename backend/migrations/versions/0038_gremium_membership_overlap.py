"""gremium_membership_overlap: database backing for the overlap invariant (#42, AUD-029).

No two term intervals may overlap for the same ``(principal_id, gremium_id)``. Until now
only the service checked this, which left a TOCTOU gap for two parallel inserts. This
migration adds the ``EXCLUDE`` constraint that mirrors the ORM definition in
``app/modules/admin/models.py``. The interval is half open, ``[from, until)``, and NULL
means plus or minus infinity. The constraint needs the ``btree_gist`` extension.

Before it adds the constraint, the migration cleans up any existing overlap in a
deterministic way. Without that cleanup ``ADD CONSTRAINT`` fails. For each overlapping
pair the membership with the later start survives and the older one goes, with ``id`` as
the tie break. The deleted rows are NOT recoverable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0038_gremium_membership_overlap"
down_revision: str | None = "0037_applicant_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Clean up existing overlaps before the constraint applies. Keep the membership
    #    with the later start in each pair. The smaller id loses the tie break, so the
    #    cleanup stays deterministic.
    op.execute(
        """
        DELETE FROM gremium_membership a
        USING gremium_membership b
        WHERE a.principal_id = b.principal_id
          AND a.gremium_id = b.gremium_id
          AND a.id <> b.id
          AND tstzrange(coalesce(a.valid_from, '-infinity'),
                        coalesce(a.valid_until, 'infinity'), '[)')
              && tstzrange(coalesce(b.valid_from, '-infinity'),
                           coalesce(b.valid_until, 'infinity'), '[)')
          AND (
               coalesce(a.valid_from, '-infinity') < coalesce(b.valid_from, '-infinity')
               OR (coalesce(a.valid_from, '-infinity') = coalesce(b.valid_from, '-infinity')
                   AND a.id < b.id)
              )
        """
    )

    # 2) A GIST EXCLUDE over equality columns (=) needs btree_gist. If the deploy role
    #    lacks the rights, a database admin must create the extension first. This step
    #    is then a no-op (compare 0027 and pg_trgm).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # 3) The EXCLUDE constraint matches the ExcludeConstraint in the ORM exactly. On a
    #    fresh database 0001 already created the table WITH this constraint, because
    #    ``create_all`` emits it from the model. This step is then a no-op. On an
    #    existing database 0001 ran before the model change and left the table WITHOUT
    #    the constraint, so this step adds it. ``ADD CONSTRAINT`` has no
    #    ``IF NOT EXISTS``, hence the existence check over ``pg_constraint``.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ex_gremium_membership_no_overlap'
                  AND conrelid = 'gremium_membership'::regclass
            ) THEN
                ALTER TABLE gremium_membership
                ADD CONSTRAINT ex_gremium_membership_no_overlap
                EXCLUDE USING gist (
                    principal_id WITH =,
                    gremium_id WITH =,
                    tstzrange(coalesce(valid_from, '-infinity'),
                              coalesce(valid_until, 'infinity'), '[)') WITH &&
                );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE gremium_membership "
        "DROP CONSTRAINT IF EXISTS ex_gremium_membership_no_overlap"
    )
    # btree_gist stays installed on purpose, because other objects may use it. This
    # mirrors how 0027 treats pg_trgm. Deleted overlaps are not recoverable.
