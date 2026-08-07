"""cd_variants: admin-managed corporate-design variants (#cd-variants).

A CD variant controls the logos of a rendered document — the title-page set and
the footer set — plus a display name. It controls no color and no font. The
platform can hold arbitrarily many of them.

* `cd_variant` — key (slug, unique, immutable), display name, base variant
  (`report` or `protocol`, the pytex document shape).
* `cd_variant_logo` — one logo per row, in a slot (`title` or `footer`) at a
  position. A row is EITHER a vendored pytex logo name OR an uploaded object in
  MinIO. `ck_cd_variant_logo_source` holds that exactly-one-of rule.
* `gremium.cd_variant_id` replaces the free-text `gremium.cd_variant`. The FK is
  RESTRICT, so a variant that a Gremium still uses cannot be deleted.
* The seed reproduces the five variants of before with vendored logo names only,
  so it writes nothing into the object storage. The mapping matches
  `pytex_hsrtreport.variants` (DEFAULT_LOGOS / FOOTER_LOGOS): stupa, asta and
  echo are protocols with their own logo, makers is a report with MAKERS on the
  title page and MAKERS-RAlign in the footer, report is the plain INF report.
* `admin.cd_variants` gates the new admin page. The migration seeds it to the
  `admin` role, which holds the full catalog.

Every statement is idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING` or a
guarded `DO` block). On a fresh database `0001_baseline` already creates the two
tables and the column through `Base.metadata.create_all`, and `0002_seed`
already writes the five rows. On an installed database this revision creates and
backfills them.

`downgrade` restores the free-text column and drops `cd_variant_id`. It leaves
the two tables in place on purpose: they belong to the model metadata, so
`0001_baseline.downgrade` (`drop_all`) owns them, and `0002_seed.downgrade`
still needs them to delete its own seeded rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "ec167d091656"
down_revision: str | None = "b7c41d2e9f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (key, display name, base variant, title logos, footer logos). Keep in sync
# with CD_VARIANTS in 0002_seed.py.
_SEED: tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("stupa", "StuPa", "protocol", ("STUPA",), ("STUPA",)),
    ("asta", "AStA", "protocol", ("ASTA",), ("ASTA",)),
    ("echo", "ECHO", "protocol", ("ECHO",), ("ECHO",)),
    ("makers", "MAKERS", "report", ("MAKERS",), ("MAKERS-RAlign",)),
    ("report", "HSRT INF", "report", ("INF",), ()),
)


def _seed_statements() -> tuple[str, ...]:
    """Build the idempotent INSERTs for the five variants and their logos.

    Every literal comes from the constant above, so no user input reaches the
    statement text.

    All logos of one variant go in ONE statement. The ``NOT EXISTS`` guard would
    otherwise see the row that the previous statement wrote and skip the rest of
    the set.
    """
    stmts: list[str] = [
        "INSERT INTO cd_variant (key, name, base_variant) "
        f"VALUES ('{key}', '{name}', '{base}') ON CONFLICT (key) DO NOTHING"
        for key, name, base, _title, _footer in _SEED
    ]
    for key, _name, _base, title, footer in _SEED:
        rows = [
            f"('{slot}'::text, {index}, '{logo}'::text)"
            for slot, names in (("title", title), ("footer", footer))
            for index, logo in enumerate(names)
        ]
        if not rows:  # pragma: no cover - every seeded variant carries a logo
            continue
        # Seed the logos only for a variant that has none yet. On a fresh database
        # 0002_seed already wrote them.
        stmts.append(
            'INSERT INTO cd_variant_logo (variant_id, slot, "position", vendored_name) '
            "SELECT v.id, x.slot, x.pos, x.name FROM cd_variant v "
            f"CROSS JOIN (VALUES {', '.join(rows)}) AS x (slot, pos, name) "
            f"WHERE v.key = '{key}' AND NOT EXISTS ("
            "SELECT 1 FROM cd_variant_logo l WHERE l.variant_id = v.id)"
        )
    return tuple(stmts)


_CREATE_VARIANT = """
CREATE TABLE IF NOT EXISTS cd_variant (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    key text NOT NULL,
    name text NOT NULL,
    base_variant text NOT NULL DEFAULT 'report',
    CONSTRAINT pk_cd_variant PRIMARY KEY (id),
    CONSTRAINT uq_cd_variant_key UNIQUE (key),
    CONSTRAINT ck_cd_variant_base_variant
        CHECK (base_variant IN ('report', 'protocol'))
)
"""

_CREATE_LOGO = """
CREATE TABLE IF NOT EXISTS cd_variant_logo (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    variant_id uuid NOT NULL,
    slot text NOT NULL,
    "position" integer NOT NULL DEFAULT 0,
    vendored_name text,
    object_key text,
    file_name text,
    mime text,
    size integer,
    CONSTRAINT pk_cd_variant_logo PRIMARY KEY (id),
    CONSTRAINT fk_cd_variant_logo_variant_id_cd_variant
        FOREIGN KEY (variant_id) REFERENCES cd_variant (id) ON DELETE CASCADE,
    CONSTRAINT ck_cd_variant_logo_slot CHECK (slot IN ('title', 'footer')),
    CONSTRAINT ck_cd_variant_logo_source
        CHECK ((vendored_name IS NULL) <> (object_key IS NULL))
)
"""

_LOGO_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_cd_variant_logo_variant_id_slot_position "
    'ON cd_variant_logo (variant_id, slot, "position")'
)

_ADD_FK = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_gremium_cd_variant_id_cd_variant'
    ) THEN
        ALTER TABLE gremium ADD CONSTRAINT fk_gremium_cd_variant_id_cd_variant
            FOREIGN KEY (cd_variant_id) REFERENCES cd_variant (id) ON DELETE RESTRICT;
    END IF;
END $$;
"""

# Backfill from the free-text column. The DO block guards it, because a fresh
# database never had that column: create_all builds `gremium` from the current
# model, and the model no longer holds it.
_BACKFILL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'gremium' AND column_name = 'cd_variant'
    ) THEN
        UPDATE gremium g SET cd_variant_id = v.id
        FROM cd_variant v
        WHERE v.key = g.cd_variant AND g.cd_variant_id IS NULL;
    END IF;
END $$;
"""

_RESTORE = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'gremium' AND column_name = 'cd_variant_id'
    ) THEN
        UPDATE gremium g SET cd_variant = v.key
        FROM cd_variant v WHERE v.id = g.cd_variant_id;
    END IF;
END $$;
"""

_UPGRADE: tuple[str, ...] = (
    _CREATE_VARIANT,
    _CREATE_LOGO,
    _LOGO_INDEX,
    *_seed_statements(),
    "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS cd_variant_id uuid",
    _ADD_FK,
    _BACKFILL,
    "ALTER TABLE gremium DROP COLUMN IF EXISTS cd_variant",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'admin.cd_variants' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'admin.cd_variants'",
    (
        "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS cd_variant text "
        "NOT NULL DEFAULT 'stupa'"
    ),
    _RESTORE,
    (
        "ALTER TABLE gremium DROP CONSTRAINT IF EXISTS "
        "fk_gremium_cd_variant_id_cd_variant"
    ),
    "ALTER TABLE gremium DROP COLUMN IF EXISTS cd_variant_id",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
