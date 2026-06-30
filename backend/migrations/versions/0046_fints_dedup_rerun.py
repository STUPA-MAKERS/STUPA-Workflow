"""fints_dedup_rerun: Dedup-Bereinigung erneut anstoßen (#fints-dedup).

Eine frühere Version von 0045 lief bereits auf der DB und ist in ``alembic_version`` als angewandt
markiert — alembic führt sie NICHT erneut aus, auch nach korrigiertem Code. Damit die korrigierte,
rohdaten-basierte Bereinigung (:func:`bank_maintenance.dedup_staged_lines`) auf bestehenden Daten
greift, ruft sie diese **neue** Revision auf. Identische, idempotente Logik wie 0045 — kein
dupliziertes Skript, nur ein erneuter Aufruf derselben Funktion.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0046_fints_dedup_rerun"
down_revision: str | None = "0045_fints_dedup_staged"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.modules.budget.bank_maintenance import dedup_staged_lines

    dedup_staged_lines(op.get_bind())


def downgrade() -> None:
    pass
