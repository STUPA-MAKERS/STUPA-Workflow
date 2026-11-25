"""Bestellungen: a Bestellung is a kind of link end.

The upgrade (F/finance/orders/002887):

1. adds the kind ``order`` to the kind checks of ``link``.
2. adds the trigger ``link_drop_ends`` to ``purchase_order``, so a deleted Bestellung
   takes its links with it.

Every step is idempotent. A fresh database already gets the checks from the
``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade removes the links with a Bestellung as an end, because the old kind checks
do not accept them.

Revision ID: 5e8a1c7d3f42
Revises: 9d2f6a4b81c7
Create Date: 2026-11-24 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5e8a1c7d3f42"
down_revision: str | None = "9d2f6a4b81c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The link kinds before this revision.
_OLD: tuple[str, ...] = (
    "application",
    "meeting",
    "agenda_item",
    "vote",
    "appointment",
    "gremium",
    "invoice",
    "expense",
    "budget",
    "ticket",
    "todo",
    "paperless",
)


def _kind_checks(kinds: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{kind}'" for kind in kinds)
    for side in ("a", "b"):
        op.execute(f"ALTER TABLE link DROP CONSTRAINT IF EXISTS ck_link_{side}_kind")
        op.execute(
            f"ALTER TABLE link ADD CONSTRAINT ck_link_{side}_kind CHECK ({side}_kind IN ({listed}))"
        )


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    _kind_checks((*_OLD, "order"))
    op.execute("DROP TRIGGER IF EXISTS link_drop_ends ON purchase_order")
    op.execute(
        "CREATE TRIGGER link_drop_ends AFTER DELETE ON purchase_order "
        "FOR EACH ROW EXECUTE FUNCTION link_drop_ends('order')"
    )


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    op.execute("DELETE FROM link WHERE a_kind = 'order' OR b_kind = 'order'")
    op.execute("DROP TRIGGER IF EXISTS link_drop_ends ON purchase_order")
    _kind_checks(_OLD)
