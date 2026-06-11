"""Typ-Flow-Reste entfernen (#28-Abschluss): nur noch der globale Flow.

Migration 0006 hat den Cutover erzwungen (eine globale ``flow_version``-Zeile,
Alt-Versionen gelöscht); die Spalten/Constraints des alten Per-Typ-Modells
existierten aber weiter. Jetzt fallen:

* ``application_type.active_flow_version_id``
* ``flow_version.application_type_id`` (abhängige Indizes/Constraints fallen mit)

Neu: ``version`` unique + genau EIN aktiver Flow (partial unique auf ``active``).
Bestands-Daten werden vorher passend gemacht (Aktiv-Duplikate deaktivieren,
Versionsnummern-Duplikate neu durchnummerieren). Idempotent (``IF [NOT] EXISTS``).
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
    -- Bestands-DBs können mehrere aktive Zeilen tragen (Per-Typ-Aktive aus der
    -- Zeit vor dem 0006-Cutover bzw. einer älteren 0006-Variante). Vor dem
    -- partial unique Index darf nur EINE aktive Zeile übrig sein: bevorzugt die
    -- globale (application_type_id IS NULL), sonst die höchste Version.
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

# UNIQUE (version) braucht eindeutige Versionsnummern; Per-Typ-Flows konnten
# dieselbe Nummer mehrfach vergeben. Deterministisch neu durchnummerieren
# (Reihenfolge bleibt: alte Nummer, dann Alter) — No-op ohne Duplikate. Läuft
# NACH den Spalten-/Constraint-Drops, damit kein altes Unique transient bricht.
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
    # Abhängige Indizes/Unique-Constraints (…one_active_per_type, (type, version))
    # fallen mit der Spalte.
    "ALTER TABLE flow_version DROP COLUMN IF EXISTS application_type_id",
    "DROP INDEX IF EXISTS uq_flow_version_one_active_global",
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_version_one_active_global "
        "ON flow_version (active) WHERE active"
    ),
    # Beide möglichen Namen droppen (Bestands-DB: Postgres-Default-Name;
    # frische DB: Namenskonvention der Models), dann kanonisch neu anlegen.
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
    # Nicht umkehrbar (wie 0006): die Typ-Flow-Daten sind seit dem 0006-Cutover
    # weg; die Spalten wiederherzustellen brächte nur tote Strukturen zurück und
    # bräche zudem den drop_all-Downgrade der Baseline (FK auf application_type,
    # den die aktuellen Models nicht mehr kennen). Bewusst No-op.
    pass
