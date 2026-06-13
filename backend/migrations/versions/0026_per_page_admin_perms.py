"""Per-Seite-Admin-Permissions (#per-page-admin) — Bestands-Zuweisungen remappen.

Die zuvor von ``admin.roles`` mitgegatete Personen-/Zugriffsverwaltung wird je
Admin-Seite getrennt; ``admin.deadlines`` löst die Fristen-Seite aus ``admin.types``:

* ``admin.roles`` → behält /admin/roles; Inhaber erhalten zusätzlich
  ``admin.users`` + ``admin.group_mappings`` + ``admin.gremium_roles`` +
  ``admin.delegations`` (bisheriger Funktionsumfang bleibt exakt erhalten).
* ``admin.types`` → bleibt (Antragstypen/Forms/Flows); Inhaber erhalten zusätzlich
  ``admin.deadlines`` (die Fristen-Seite war bisher unter ``admin.types``).

Idempotent (``ON CONFLICT DO NOTHING``). ``admin.roles``/``admin.types`` bleiben
bestehen — kein DELETE.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_per_page_admin_perms"
down_revision: str | None = "0025_invoices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fanout(old: str, new: tuple[str, ...]) -> list[str]:
    """``old`` → ``new``-Rechte für alle Rollen, die ``old`` halten (additiv)."""
    return [
        (
            "INSERT INTO role_permission (role_id, permission) "
            f"SELECT role_id, '{n}' FROM role_permission "
            f"WHERE permission = '{old}' "
            "ON CONFLICT DO NOTHING"
        )
        for n in new
    ]


_NEW_FROM_ROLES = (
    "admin.users",
    "admin.group_mappings",
    "admin.gremium_roles",
    "admin.delegations",
)

_UPGRADE: tuple[str, ...] = (
    *_fanout("admin.roles", _NEW_FROM_ROLES),
    *_fanout("admin.types", ("admin.deadlines",)),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission IN "
    "('admin.users', 'admin.group_mappings', 'admin.gremium_roles', "
    "'admin.delegations', 'admin.deadlines')",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
