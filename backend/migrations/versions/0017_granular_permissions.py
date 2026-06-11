"""Granularere globale Permissions (#6) — Bestands-Zuweisungen remappen.

Aufteilung (shared/permissions.py):
* ``admin.config``  → ``admin.site`` + ``admin.gremien`` + ``admin.types``
* ``budget.manage`` → ``budget.structure`` + ``budget.book``
* ``meeting.manage`` bleibt; Inhaber erhalten zusätzlich ``protocol.finalize``
* ``audit.read``     bleibt; Inhaber erhalten zusätzlich ``audit.verify``

Bestehende Rollen behalten damit exakt ihren bisherigen Funktionsumfang.
Idempotent (``ON CONFLICT DO NOTHING`` / wiederholbare DELETEs).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_granular_permissions"
down_revision: str | None = "0016_notification_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fanout(old: str, new: tuple[str, ...]) -> list[str]:
    """``old`` → ``new``-Rechte für alle Rollen, die ``old`` halten."""
    stmts = [
        (
            "INSERT INTO role_permission (role_id, permission) "
            f"SELECT role_id, '{n}' FROM role_permission "
            f"WHERE permission = '{old}' "
            "ON CONFLICT DO NOTHING"
        )
        for n in new
    ]
    return stmts


_UPGRADE: tuple[str, ...] = (
    *_fanout("admin.config", ("admin.site", "admin.gremien", "admin.types")),
    "DELETE FROM role_permission WHERE permission = 'admin.config'",
    *_fanout("budget.manage", ("budget.structure", "budget.book")),
    "DELETE FROM role_permission WHERE permission = 'budget.manage'",
    *_fanout("meeting.manage", ("protocol.finalize",)),
    *_fanout("audit.read", ("audit.verify",)),
)

_DOWNGRADE: tuple[str, ...] = (
    *_fanout("admin.site", ("admin.config",)),
    *_fanout("admin.gremien", ("admin.config",)),
    *_fanout("admin.types", ("admin.config",)),
    "DELETE FROM role_permission WHERE permission IN "
    "('admin.site', 'admin.gremien', 'admin.types')",
    *_fanout("budget.structure", ("budget.manage",)),
    *_fanout("budget.book", ("budget.manage",)),
    "DELETE FROM role_permission WHERE permission IN "
    "('budget.structure', 'budget.book')",
    "DELETE FROM role_permission WHERE permission = 'protocol.finalize'",
    "DELETE FROM role_permission WHERE permission = 'audit.verify'",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
