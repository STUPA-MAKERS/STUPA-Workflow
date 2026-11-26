"""Status lists: the permissions of the pages are named for statuses, not phases.

The pages "Bestellphasen" and "Veranstaltungsphasen" are now "Bestellzustände" and
"Veranstaltungszustände" (F/administration/admin/003035), and their permissions
``admin.order_phases`` and ``admin.event_phases`` become ``admin.order_statuses`` and
``admin.event_statuses``. The upgrade renames each grant in ``role_permission``, so a role
keeps its right. A role that already holds the new name keeps one row.

The downgrade renames them back.

Revision ID: b3e7d1c9a402
Revises: 7c4e2a9d1b85
Create Date: 2026-11-26 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e7d1c9a402"
down_revision: str | None = "7c4e2a9d1b85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMES: tuple[tuple[str, str], ...] = (
    ("admin.order_phases", "admin.order_statuses"),
    ("admin.event_phases", "admin.event_statuses"),
)


def _rename(old: str, new: str) -> None:
    """Move each grant of ``old`` to ``new``."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO role_permission (role_id, permission) "
            "SELECT role_id, :new FROM role_permission WHERE permission = :old "
            "ON CONFLICT DO NOTHING"
        ),
        {"old": old, "new": new},
    )
    bind.execute(sa.text("DELETE FROM role_permission WHERE permission = :old"), {"old": old})


def upgrade() -> None:
    """Rename the grants to the names for statuses."""
    for old, new in _NAMES:
        _rename(old, new)


def downgrade() -> None:
    """Rename the grants back to the names for phases."""
    for old, new in _NAMES:
        _rename(new, old)
