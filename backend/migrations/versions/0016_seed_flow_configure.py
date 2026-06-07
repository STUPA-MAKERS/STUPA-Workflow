"""admin: grant flow.configure to admin-role (Bugfix #71 Flow-Builder »kein Zugriff«)

Revision ID: 0016_seed_flow_configure
Revises: 0015_role_assignment_tz
Create Date: 2026-06-07 00:00:16

Der Flow-Builder (FE-Route ``/admin/flow``, ``flow-editor``) ist per RBAC-Guard auf
die Permission ``flow.configure`` gegated (``app.routes.ts`` → ``data.permission``).
Diese Permission war jedoch in 0003 **nicht** an die ``admin``-Rolle geseedet — exakt
dieselbe Seed-Lücke wie schon bei ``form.configure`` (in 0010 nachgezogen). Folge:
unter **echter** OIDC-Auth (ohne Mock-Interceptor, der ``flow.configure`` künstlich
injiziert) sieht selbst ein Admin »kein Zugriff« auf den Flow-Builder.

Diese Revision seedet ``flow.configure`` idempotent an die ``admin``-Rolle nach
(``INSERT … WHERE NOT EXISTS``), analog zu ``form.configure`` in 0010. ``flow.configure``
ist ein dokumentierter Permission-Key (``sds/api.md §1``).

Lineare Kette: ``down_revision`` = ``0015_role_assignment_tz`` → ``alembic heads`` = EIN Head.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_seed_flow_configure"
down_revision: str | None = "0015_role_assignment_tz"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_ROLE_ID = "00000000-0000-0000-0000-0000000000a1"
_FLOW_CONFIGURE = "flow.configure"

_role_permission = sa.table(
    "role_permission",
    sa.column("role_id", sa.Uuid),
    sa.column("permission", sa.Text),
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO role_permission (role_id, permission) "
            "SELECT CAST(:rid AS uuid), :perm WHERE NOT EXISTS ("
            "  SELECT 1 FROM role_permission "
            "  WHERE role_id = CAST(:rid AS uuid) AND permission = :perm)"
        ).bindparams(rid=_ADMIN_ROLE_ID, perm=_FLOW_CONFIGURE)
    )


def downgrade() -> None:
    op.execute(
        sa.delete(_role_permission).where(
            _role_permission.c.role_id == _ADMIN_ROLE_ID,
            _role_permission.c.permission == _FLOW_CONFIGURE,
        )
    )
