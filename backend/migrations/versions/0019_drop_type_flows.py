"""Typ-Flow-Reste entfernen (#28-Abschluss): nur noch der globale Flow.

Migration 0006 hat den Cutover erzwungen (eine globale ``flow_version``-Zeile,
Alt-Versionen gelöscht); die Spalten/Constraints des alten Per-Typ-Modells
existierten aber weiter. Jetzt fallen:

* ``application_type.active_flow_version_id``
* ``flow_version.application_type_id`` (abhängige Indizes/Constraints fallen mit)

Neu: ``version`` unique + genau EIN aktiver Flow (partial unique auf ``active``).
Idempotent (``IF [NOT] EXISTS``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019_drop_type_flows"
down_revision: str | None = "0018_notification_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE application_type DROP COLUMN IF EXISTS active_flow_version_id",
    # Abhängige Indizes/Unique-Constraints (…one_active_per_type, (type, version))
    # fallen mit der Spalte.
    "ALTER TABLE flow_version DROP COLUMN IF EXISTS application_type_id",
    "DROP INDEX IF EXISTS uq_flow_version_one_active_global",
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_version_one_active_global "
        "ON flow_version (active) WHERE active"
    ),
    "ALTER TABLE flow_version DROP CONSTRAINT IF EXISTS flow_version_version_key",
    (
        "ALTER TABLE flow_version "
        "ADD CONSTRAINT flow_version_version_key UNIQUE (version)"
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
