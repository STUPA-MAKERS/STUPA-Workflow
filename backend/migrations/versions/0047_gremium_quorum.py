"""gremium: add quorum_percent (#committee-quorum)

Revision ID: 0047_gremium_quorum
Revises: 0046_state_color
Create Date: 2026-06-09 19:00:00

Ein Gremium bekommt ein optionales Default-Quorum (``quorum_percent``, 0–100 % der
Stimmberechtigten, die teilnehmen müssen). NULL = kein Default. Es dient als Vorbelegung
des Quorums von Abstimmungen, die für dieses Gremium geöffnet werden. Idempotent
(Inspector-Check). ``down_revision`` = ``0046_state_color``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047_gremium_quorum"
down_revision: str | None = "0046_state_color"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("gremium")}
    if "quorum_percent" not in cols:
        op.add_column(
            "gremium", sa.Column("quorum_percent", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("gremium")}
    if "quorum_percent" in cols:
        op.drop_column("gremium", "quorum_percent")
