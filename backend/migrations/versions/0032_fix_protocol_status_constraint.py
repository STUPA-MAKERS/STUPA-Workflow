"""Protocol-Status-CHECK normalisieren (Fix: ``rendering`` wird abgelehnt).

Bug: Migration 0001 (``create_all``) legte den CHECK über die Namens-Konvention als
``ck_protocol_protocol_status`` mit dem damaligen Wertebereich (``draft``/``final``) an.
Migration 0011 versuchte ihn per ``DROP CONSTRAINT IF EXISTS protocol_status`` zu
ersetzen — traf aber den konventions-benannten Constraint NICHT und legte einen
zweiten (``protocol_status``) an. Auf so gebauten DBs überlebt der alte
``ck_protocol_protocol_status``-CHECK ohne ``rendering`` → ``finalize`` (Status →
``rendering``) wirft 500 (CheckViolation).

Fix: beide möglichen Constraint-Namen droppen und EINEN Constraint unter dem
Konventions-Namen ``ck_protocol_protocol_status`` mit dem vollen Wertebereich neu
anlegen — damit ``create_all`` (frisches Schema) und Migrationen denselben Namen +
dieselbe Bedingung führen. Idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0032_fix_protocol_status_ck"
down_revision: str | None = "0031_non_public_tops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS protocol_status",
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS ck_protocol_protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT ck_protocol_protocol_status "
        "CHECK (status IN ('draft','rendering','final'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # Symmetrisch: Constraint behalten, aber wieder unter dem 0011-Namen führen.
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS ck_protocol_protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT protocol_status "
        "CHECK (status IN ('draft','rendering','final'))"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
