"""webhook_delivery.idempotency_key + unique(webhook_id, idempotency_key) (T-19)

Revision ID: 0012_webhook_idempotency
Revises: 0011_render_job_table
Create Date: 2026-06-07 00:00:12

Der Dispatch-Motor (T-19) entkoppelt die **Event-Instanz** vom Versand: ein Flow-
Retry desselben Status-Events darf **keine** zweite ``webhook_delivery`` anlegen.
Dazu trägt jede Delivery einen ``idempotency_key`` (stabil über Antrag/Status-Event/
Action-Position/Webhook); ``unique(webhook_id, idempotency_key)`` macht das Anlegen
idempotent. ``NULL`` ist erlaubt (keine Dedup, z. B. manueller Re-Dispatch) und
kollidiert in Postgres nie mit sich selbst.

Idempotent: auf einem **frischen** Schema hat ``Base.metadata.create_all`` (0002)
Spalte + Constraint bereits angelegt; diese Revision prüft daher per Inspector und
legt nur Fehlendes nach (für vor-T-19 migrierte Schemata).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_webhook_idempotency"
down_revision: str | None = "0011_render_job_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "webhook_delivery"
_COLUMN = "idempotency_key"
_CONSTRAINT = "uq_webhook_delivery_idempotency"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if _COLUMN not in columns:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))

    constraints = {uc["name"] for uc in inspector.get_unique_constraints(_TABLE)}
    if _CONSTRAINT not in constraints:
        op.create_unique_constraint(
            _CONSTRAINT, _TABLE, ["webhook_id", _COLUMN]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    constraints = {uc["name"] for uc in inspector.get_unique_constraints(_TABLE)}
    if _CONSTRAINT in constraints:
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")

    columns = {col["name"] for col in inspector.get_columns(_TABLE)}
    if _COLUMN in columns:
        op.drop_column(_TABLE, _COLUMN)
