"""members_notify: the gremium permission ``members.notify`` on the forced roles.

The upgrade adds ``members.notify`` to the forced roles ``vorstand`` and ``manager`` of
every Gremium, because a new forced permission reaches only new Gremien through the role
catalog, and the backfill of a listing adds missing roles, never missing permissions.
Idempotent.

The downgrade removes ``members.notify`` from every gremium role.

Revision ID: c4e8a1f07b52
Revises: d7e2a9c41b38
Create Date: 2026-11-20 04:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c4e8a1f07b52"
down_revision: str | None = "d7e2a9c41b38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(
        "UPDATE gremium_role SET permissions = permissions || '[\"members.notify\"]'::jsonb "
        "WHERE key IN ('vorstand', 'manager') AND NOT permissions ? 'members.notify'"
    )


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    op.execute(
        "UPDATE gremium_role SET permissions = permissions - 'members.notify' "
        "WHERE permissions ? 'members.notify'"
    )
