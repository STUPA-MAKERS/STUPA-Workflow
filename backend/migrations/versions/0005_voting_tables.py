"""voting: vote/ballot/voted_marker/secret_ballot (T-15)

Revision ID: 0005_voting_tables
Revises: 0004_budget_entry_and_views
Create Date: 2026-06-06 00:00:05

Wie alle Modul-Tabellen entstehen die Voting-Tabellen auf einem **frischen** Schema
bereits über ``Base.metadata.create_all`` in 0002 (Single-Source via ``app.models``).
Für bereits vor T-15 migrierte Schemata legt diese Revision sie **idempotent** nach:
``create_all(..., checkfirst=True)`` erzeugt nur fehlende Tabellen, überspringt also
auf frischen DBs die bereits vorhandenen.

Die Permissions ``vote.manage`` / ``vote.cast`` sind bereits in 0003 geseedet.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker

revision: str = "0005_voting_tables"
down_revision: str | None = "0004_budget_entry_and_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [m.__table__ for m in (Vote, Ballot, VotedMarker, SecretBallot)]


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=_TABLES, checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), tables=_TABLES, checkfirst=True)
