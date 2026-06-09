"""Permission-Rework (#28): transition/meeting carry-over + drop dead perms

Revision ID: 0039_permission_rework
Revises: 0038_state_kind_cleanup
Create Date: 2026-06-09 12:30:00

Reworkter Permission-Katalog (16 Keys). Migrationsschritte (idempotent):

1. Jede Rolle mit ``application.manage`` erhält zusätzlich ``application.transition``
   (manuelle Flow-Übergänge sind jetzt eine eigene Permission, vorher ``manage``).
2. Jede Rolle mit ``protocol.write`` erhält ``meeting.manage`` (Protokoll-Endpunkte
   gaten jetzt darauf).
3. Tote Permissions aus ``role_permission`` entfernen:
   ``application.update``, ``protocol.write``, ``protocol.manage``.

``down_revision`` = ``0038_state_kind_cleanup``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_permission_rework"
down_revision: str | None = "0038_state_kind_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _carry_over(source: str, target: str) -> None:
    """``target`` jeder Rolle geben, die ``source`` hält (idempotent)."""
    op.execute(
        sa.text(
            "INSERT INTO role_permission (role_id, permission) "
            "SELECT rp.role_id, :target FROM role_permission rp "
            "WHERE rp.permission = :source AND NOT EXISTS ("
            "  SELECT 1 FROM role_permission x "
            "  WHERE x.role_id = rp.role_id AND x.permission = :target)"
        ).bindparams(source=source, target=target)
    )


def upgrade() -> None:
    _carry_over("application.manage", "application.transition")
    _carry_over("protocol.write", "meeting.manage")
    op.execute(
        sa.text(
            "DELETE FROM role_permission WHERE permission IN "
            "('application.update','protocol.write','protocol.manage')"
        )
    )


def downgrade() -> None:
    # Best-effort: protocol.write den meeting.manage-Rollen zurückgeben. Die übrigen
    # gedroppten Keys + application.transition lassen sich nicht eindeutig invertieren.
    _carry_over("meeting.manage", "protocol.write")
