"""Paperless: the filing of a file of a ticket.

The upgrade widens the check of ``paperless_filing.kind`` by ``ticket_file``, the file
of a ticket that a person files with the action "In Paperless ablegen".

The step is idempotent. A fresh database already gets the check from the ``create_all``
baseline (0001), because the model sits in ``app.models``.

The downgrade deletes each ``ticket_file`` row, because the older schema has no such
kind. The documents stay in Paperless.

Revision ID: c5d81f3a2e47
Revises: b7e42d9a6c15
Create Date: 2026-11-23 23:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c5d81f3a2e47"
down_revision: str | None = "b7e42d9a6c15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'protocol','protocol_public','application','attachment','plan'"

_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE paperless_filing DROP CONSTRAINT IF EXISTS ck_paperless_filing_kind",
    f"ALTER TABLE paperless_filing ADD CONSTRAINT ck_paperless_filing_kind "
    f"CHECK (kind IN ({_KINDS},'ticket_file'))",
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM paperless_filing WHERE kind = 'ticket_file'",
    "ALTER TABLE paperless_filing DROP CONSTRAINT IF EXISTS ck_paperless_filing_kind",
    f"ALTER TABLE paperless_filing ADD CONSTRAINT ck_paperless_filing_kind "
    f"CHECK (kind IN ({_KINDS}))",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
