"""Paperless: a Paperless document is a kind of link end.

The upgrade (§F/integrations/paperless/002763, 002765, 002767):

1. creates ``paperless_document``: one row per linked document, with its number in
   Paperless and the title, the type and the date from the moment of the newest link.
2. adds ``paperless_settings.link_enabled``, the switch `Paperless-Dokumente verknüpfen`.
3. adds the kind ``paperless`` to the kind checks of ``link`` and adds the check
   ``ck_link_one_paperless``: two Paperless documents do not link each other.
4. adds the trigger ``link_drop_ends`` to ``paperless_document``, so a deleted row takes
   its links with it.

Every step is idempotent. A fresh database already gets the table and the checks from
the ``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade removes the links with a Paperless end, because the old kind checks do
not accept them.

Revision ID: b9e2c47f1a36
Revises: c5d81f3a2e47
Create Date: 2026-11-23 18:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b9e2c47f1a36"
down_revision: str | None = "c5d81f3a2e47"
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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS paperless_document (
            id uuid CONSTRAINT pk_paperless_document PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id integer NOT NULL
                CONSTRAINT uq_paperless_document_document_id UNIQUE,
            title text NOT NULL DEFAULT '',
            document_type text,
            created date,
            stored_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "ALTER TABLE paperless_settings "
        "ADD COLUMN IF NOT EXISTS link_enabled BOOLEAN NOT NULL DEFAULT false"
    )
    _kind_checks((*_OLD, "paperless"))
    op.execute("ALTER TABLE link DROP CONSTRAINT IF EXISTS ck_link_one_paperless")
    op.execute(
        "ALTER TABLE link ADD CONSTRAINT ck_link_one_paperless "
        "CHECK (NOT (a_kind = 'paperless' AND b_kind = 'paperless'))"
    )
    op.execute("DROP TRIGGER IF EXISTS link_drop_ends ON paperless_document")
    op.execute(
        "CREATE TRIGGER link_drop_ends AFTER DELETE ON paperless_document "
        "FOR EACH ROW EXECUTE FUNCTION link_drop_ends('paperless')"
    )


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    op.execute("DELETE FROM link WHERE a_kind = 'paperless' OR b_kind = 'paperless'")
    op.execute("ALTER TABLE link DROP CONSTRAINT IF EXISTS ck_link_one_paperless")
    _kind_checks(_OLD)
    op.execute("DROP TABLE IF EXISTS paperless_document")
    op.drop_column("paperless_settings", "link_enabled")
