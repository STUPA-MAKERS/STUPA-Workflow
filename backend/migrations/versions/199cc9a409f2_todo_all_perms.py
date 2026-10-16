"""To-dos: grant ``todo.all`` and ``todo.read_all`` to the role ``admin``.

Two new global permissions of the to-do boards: ``todo.all`` reads and writes the
cards of every gremium and team board, ``todo.read_all`` only reads them. Neither
reaches a personal board or configures a board. The admin bypass grants both
anyway; the rows make the role page show them. Other roles get them only by hand.

No table changes. The statement is idempotent (``ON CONFLICT DO NOTHING``).

The downgrade removes the permission rows.

Revision ID: 199cc9a409f2
Revises: 071d20ab0e10
Create Date: 2026-10-16 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "199cc9a409f2"
down_revision: str | None = "071d20ab0e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, p.permission FROM role r "
        "CROSS JOIN (VALUES ('todo.all'), ('todo.read_all')) AS p (permission) "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permission WHERE permission IN ('todo.all', 'todo.read_all')")
