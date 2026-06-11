"""Per-User-Benachrichtigungs-Schalter (#4-2).

``notification_preference`` speichert nur Abweichungen vom Default (alle
Arten aktiv): eine Zeile (principal, kind, enabled=false) = abgewählt.
Idempotent (``IF [NOT] EXISTS``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016_notification_preferences"
down_revision: str | None = "0015_drop_pii_anonymization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "CREATE TABLE IF NOT EXISTS notification_preference ("
        "principal_id uuid NOT NULL "
        "REFERENCES principal(id) ON DELETE CASCADE, "
        "kind text NOT NULL, "
        "enabled boolean NOT NULL DEFAULT true, "
        "PRIMARY KEY (principal_id, kind))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS notification_preference",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
