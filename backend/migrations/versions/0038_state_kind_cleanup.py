"""state.kind cleanup — nur noch 'normal' + 'vote' (#28-Redesign)

Revision ID: 0038_state_kind_cleanup
Revises: 0037_deadline_policy
Create Date: 2026-06-09 12:00:00

approval/decision-State-Arten entfallen (durch manuelle roleIs-Übergänge bzw.
automatische Guard-Übergänge abgedeckt). Pre-Alpha-Cutover: bestehende
approval/decision-States werden auf ``normal`` zurückgesetzt, alte
approval-Branches (``accept``/``reject``) auf ``NULL`` gesetzt (nur noch ``vote``
nutzt ``pass``/``fail``), danach die CheckConstraint ``state_kind`` auf
``('normal','vote')`` verengt. Idempotent. ``down_revision`` = ``0037_deadline_policy``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_state_kind_cleanup"
down_revision: str | None = "0037_deadline_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DB-Name des Constraints (Model ``CheckConstraint(name="state_kind")`` +
# Naming-Convention ⇒ ``ck_state_state_kind``). Roh-SQL mit explizitem Namen +
# ``IF EXISTS`` → idempotent, unabhängig von der Alembic-Convention.
_DB_NAME = "ck_state_state_kind"


def upgrade() -> None:
    bind = op.get_bind()
    # Cutover: approval/decision → normal (Alt-Konfiguration verwerfen).
    bind.execute(
        sa.text("UPDATE state SET kind = 'normal' WHERE kind IN ('approval','decision')")
    )
    # Alte approval-Branches (accept/reject) auf NULL — nur noch vote nutzt pass/fail.
    bind.execute(
        sa.text("UPDATE transition SET branch = NULL WHERE branch IN ('accept','reject')")
    )
    bind.execute(sa.text(f"ALTER TABLE state DROP CONSTRAINT IF EXISTS {_DB_NAME}"))
    bind.execute(
        sa.text(
            f"ALTER TABLE state ADD CONSTRAINT {_DB_NAME} "
            "CHECK (kind IN ('normal','vote'))"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(f"ALTER TABLE state DROP CONSTRAINT IF EXISTS {_DB_NAME}"))
    bind.execute(
        sa.text(
            f"ALTER TABLE state ADD CONSTRAINT {_DB_NAME} "
            "CHECK (kind IN ('normal','vote','approval','decision'))"
        )
    )
