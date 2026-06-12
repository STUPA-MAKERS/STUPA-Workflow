"""Meeting: ``closed_at`` (#14) + Permission ``meeting.delete_finalized`` (#16).

* ``meeting.closed_at`` — automatisch gesetzt, wenn die Sitzung auf ``closed``
  gestellt wird; liefert die »Ende«-Zeile der Protokoll-Titelseite.
* ``meeting.delete_finalized`` — globale Permission: Sitzungen mit FINALISIERTEM
  Protokoll löschen. Seed an die ``admin``-Rolle (Admin = alle Rechte).

Idempotent (``IF NOT EXISTS`` / ``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_meeting_delete_finalized"
down_revision: str | None = "0020_budget_hidden_in_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting ADD COLUMN IF NOT EXISTS closed_at timestamptz",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'meeting.delete_finalized' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE meeting DROP COLUMN IF EXISTS closed_at",
    "DELETE FROM role_permission WHERE permission = 'meeting.delete_finalized'",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
