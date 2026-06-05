"""core: kern-tabellen (data-model §1-3)

Revision ID: 0002_core_tables
Revises: 0001_core_extensions
Create Date: 2026-06-05 00:00:02

DB-Kern (T-06): gremium, mail_list, budget_pot/budget_field, application_type,
form_version/form_field, flow_version/state/transition, application, applicant,
submission_version, status_event, principal, role, role_permission,
role_assignment, group_mapping — inkl. FKs/ON DELETE, partial-unique-Indizes
(eine active form/flow je Typ; ein is_initial je flow) und GIN(application.data).

Quelle = `app.db.Base.metadata` (Single Source, via `app.models` befüllt). So
bleiben Modelle und Migration garantiert deckungsgleich.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base

revision: str = "0002_core_tables"
down_revision: str | None = "0001_core_extensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
