"""Paperless: drop the open jobs of Anträge, so each Antrag is filed anew at its end state.

An Antrag is filed only when it enters an end state (F/integrations/paperless/003110),
and a new try never uploads again (F/integrations/paperless/003111). Before, each change
into an approved or a denied state opened a job, and each try uploaded a copy. The
upgrade deletes each job of kind ``application`` or ``attachment`` that is not filed.
The next run of the worker opens one job for each change into an end state since the
switch went on, and `Bestehende Dokumente ablegen` opens the jobs of the older Anträge.
Filed jobs and the documents in Paperless stay. The step is idempotent: a second run
finds nothing.

Revision ID: e5a1c7d93b20
Revises: c3ee58a9d4df
Create Date: 2026-11-25 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e5a1c7d93b20"
down_revision: str | None = "c3ee58a9d4df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    op.execute(
        "DELETE FROM paperless_filing "
        "WHERE kind IN ('application', 'attachment') AND state <> 'filed'"
    )


def downgrade() -> None:
    """The deleted jobs do not come back: they would upload copies again."""
