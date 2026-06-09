"""state.kind cleanup — nur noch 'normal' + 'vote' (#28-Redesign)

Revision ID: 0038_state_kind_cleanup
Revises: 0037_deadline_policy
Create Date: 2026-06-09 12:00:00

approval/decision-State-Arten entfallen (durch manuelle roleIs-Übergänge bzw.
automatische Guard-Übergänge abgedeckt). Pre-Alpha-Cutover: bestehende
approval/decision-States werden auf ``normal`` zurückgesetzt, danach die
CheckConstraint ``state_kind`` auf ``('normal','vote')`` verengt. Idempotent.
``down_revision`` = ``0037_deadline_policy``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_state_kind_cleanup"
down_revision: str | None = "0037_deadline_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "state_kind"


def _drop_constraint_if_exists(bind: sa.Connection) -> None:
    insp = sa.inspect(bind)
    names = {c["name"] for c in insp.get_check_constraints("state")}
    if _CONSTRAINT in names:
        op.drop_constraint(_CONSTRAINT, "state", type_="check")


def upgrade() -> None:
    bind = op.get_bind()
    # Cutover: approval/decision → normal (Alt-Konfiguration verwerfen).
    bind.execute(
        sa.text(
            "UPDATE state SET kind = 'normal' WHERE kind IN ('approval','decision')"
        )
    )
    _drop_constraint_if_exists(bind)
    op.create_check_constraint(
        _CONSTRAINT, "state", "kind IN ('normal','vote')"
    )


def downgrade() -> None:
    bind = op.get_bind()
    _drop_constraint_if_exists(bind)
    op.create_check_constraint(
        _CONSTRAINT, "state", "kind IN ('normal','vote','approval','decision')"
    )
