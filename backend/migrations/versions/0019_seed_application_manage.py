"""admin: grant application.manage to admin-role (Seed-Lücke, T-40 E2E)

Revision ID: 0019_seed_application_manage
Revises: 0018_seed_default_gremium
Create Date: 2026-06-08 00:00:19

Die Statuswechsel-/Flow-Endpunkte gaten auf die Permission ``application.manage``
(``app/modules/flow/router.py`` → ``MANAGE_PERMISSION``: ``GET /applications/{}/transitions``
und ``POST /applications/{}/transition``), und das FE blendet die Statuswechsel-Aktionen
exakt auf ``application.manage`` ein (``applications-detail.component.ts`` →
``canManage = auth.can('application.manage')``). Dieser Permission-Key war jedoch in
``0003`` an **keine** Rolle geseedet (``ALL_PERMISSIONS`` enthält ``application.read/
create/update/transition``, aber NICHT ``application.manage``). Folge: unter echter
Auth kann **niemand** — auch kein Admin — einen Antrag durch den Flow schalten.

Exakt dieselbe Seed-Lücke wie bei ``form.configure`` (0010) und ``flow.configure``
(0016). Diese Revision seedet ``application.manage`` idempotent an die ``admin``-Rolle
nach (``INSERT … WHERE NOT EXISTS``).

Lineare Kette: ``down_revision`` = ``0018_seed_default_gremium`` → ``alembic heads`` = EIN Head.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_seed_application_manage"
down_revision: str | None = "0018_seed_default_gremium"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADMIN_ROLE_ID = "00000000-0000-0000-0000-0000000000a1"
_APPLICATION_MANAGE = "application.manage"

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
        ).bindparams(rid=_ADMIN_ROLE_ID, perm=_APPLICATION_MANAGE)
    )


def downgrade() -> None:
    op.execute(
        sa.delete(_role_permission).where(
            _role_permission.c.role_id == _ADMIN_ROLE_ID,
            _role_permission.c.permission == _APPLICATION_MANAGE,
        )
    )
