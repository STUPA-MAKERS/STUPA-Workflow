"""admin_features_permission: the ``admin`` role gets ``admin.features``.

The permission opens the page "Funktionen" (``/admin/features``), where an admin
switches the features of the platform on and off. The ``admin`` role holds every
permission, and the grant makes the role table show this one like every other. The
switches themselves live in the branding of ``site_config_version`` and need no column.

Revision ID: 3d95c7b1f9e6
Revises: 491d6435ea48
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "3d95c7b1f9e6"
down_revision: str | None = "491d6435ea48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grant ``admin.features`` to the ``admin`` role."""
    op.execute(
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, 'admin.features' FROM role r "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    """Remove ``admin.features`` from every role."""
    op.execute("DELETE FROM role_permission WHERE permission = 'admin.features'")
