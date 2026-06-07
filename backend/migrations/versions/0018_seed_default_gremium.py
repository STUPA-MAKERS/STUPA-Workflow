"""seed a default Gremium + ApplicationType for first-boot (Welle 2 #68/#69)

Revision ID: 0018_seed_default_gremium
Revises: 0017_role_assignment_deleg
Create Date: 2026-06-07 00:00:18

Mit »Mock aus« (#67) holt das FE Stammdaten **real**. Die Kern-Flows brauchen
mindestens ein Gremium (»Sitzung anlegen« → ``gremium_id`` Pflicht, #68) und einen
Antragstyp (Form-/Flow-Version speichern → ``application_type`` muss existieren, #69).
Eine **frische** DB hat beides nicht → die UIs hätten leere Dropdowns und das
Anlegen schlüge fehl.

Diese Revision seedet **idempotent + nicht-invasiv** je genau einen Default-Eintrag,
und zwar **nur, wenn die Tabelle leer ist** (``INSERT … WHERE NOT EXISTS (SELECT 1 …)``).
Bestehende Installationen mit echten Gremien/Typen bleiben unberührt; ein erneuter
Lauf fügt nichts doppelt hinzu. Admins können danach via ``/admin/gremien`` bzw.
``/admin/application-types`` weitere anlegen.

Lineare Kette: ``down_revision`` = ``0017_role_assignment_deleg`` (T-45/#95, nach
Rebase auf main-Head #100) → EIN ``alembic heads``. Auf 0018 umgehängt, da #95 die
0017 belegt.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_seed_default_gremium"
down_revision: str | None = "0017_role_assignment_deleg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Deterministische IDs (kein Random/Date in Migrationen) — erlauben Downgrade.
_GREMIUM_ID = "00000000-0000-0000-0000-0000000060e1"
_APP_TYPE_ID = "00000000-0000-0000-0000-0000000060e2"


def upgrade() -> None:
    # Default-Gremium nur in eine leere Tabelle (nicht-invasiv).
    op.execute(
        sa.text(
            "INSERT INTO gremium (id, name, slug, cd_variant, default_lang) "
            "SELECT CAST(:gid AS uuid), :name, :slug, :variant, :lang "
            "WHERE NOT EXISTS (SELECT 1 FROM gremium)"
        ).bindparams(
            gid=_GREMIUM_ID,
            name="StuPa",
            slug="stupa",
            variant="stupa",
            lang="de",
        )
    )
    # Default-Antragstyp nur in eine leere Tabelle; an das **erste vorhandene**
    # Gremium gehängt (0003 seedet ein Demo-Gremium → existiert i. d. R. bereits;
    # sonst greift der Insert oben). gremium_id ist nullable → notfalls ohne.
    op.execute(
        sa.text(
            "INSERT INTO application_type (id, gremium_id, key, name_i18n, has_budget) "
            "SELECT CAST(:tid AS uuid), "
            "  (SELECT id FROM gremium ORDER BY created_at, id LIMIT 1), "
            "  :key, CAST(:name AS jsonb), false "
            "WHERE NOT EXISTS (SELECT 1 FROM application_type)"
        ).bindparams(
            tid=_APP_TYPE_ID,
            key="foerderantrag",
            name='{"de": "Förderantrag", "en": "Funding application"}',
        )
    )


def downgrade() -> None:
    # Nur die geseedeten Default-Zeilen entfernen (per fixer ID).
    op.execute(
        sa.text("DELETE FROM application_type WHERE id = CAST(:tid AS uuid)").bindparams(
            tid=_APP_TYPE_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM gremium WHERE id = CAST(:gid AS uuid)").bindparams(gid=_GREMIUM_ID)
    )
