"""admin: seed budget.export / application.export permissions

Two new global permissions for the Excel exports (TASKS #2):

* ``budget.export``      → admin, finance, manager
* ``application.export`` → admin, manager

Chains after ``0042_agenda_freetext_fix`` (the two 0041 heads were linearized:
``0041_budget_color_states`` → ``0042_agenda_freetext_fix`` → here).

Revision ID: 0043_export_permissions
"""

from __future__ import annotations

from alembic import op

revision: str = "0043_export_permissions"
down_revision: str | None = "0042_agenda_freetext_fix"
branch_labels = None
depends_on = None

# (permission, [role keys that receive it])
GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("budget.export", ("admin", "finance", "manager")),
    ("application.export", ("admin", "manager")),
)


def upgrade() -> None:
    for permission, role_keys in GRANTS:
        keys = ", ".join(f"'{k}'" for k in role_keys)
        op.execute(
            "INSERT INTO role_permission (role_id, permission) "
            f"SELECT r.id, '{permission}' FROM role r "
            f"WHERE r.key IN ({keys}) "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM role_permission rp "
            f"  WHERE rp.role_id = r.id AND rp.permission = '{permission}')"
        )


def downgrade() -> None:
    for permission, _ in GRANTS:
        op.execute(f"DELETE FROM role_permission WHERE permission = '{permission}'")
