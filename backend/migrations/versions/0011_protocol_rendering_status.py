"""Protocol: Status ``rendering`` (asynchroner Protokoll-Render, T-22-Nachzug).

``finalize`` blockiert nicht mehr den Request: das Protokoll wechselt auf
``rendering``, ein arq-Worker rendert PDF + versendet die Mail und setzt
``final``; bei dauerhaftem Fehler fällt es auf ``draft`` zurück. Der
CheckConstraint ``protocol_status`` muss den neuen Zwischenzustand erlauben.
Idempotent (DROP IF EXISTS + Neuanlage).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_protocol_rendering_status"
down_revision: str | None = "0010_application_email_confirmed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT protocol_status "
        "CHECK (status IN ('draft','rendering','final'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # Laufende Renders auf Entwurf zurücksetzen, sonst verletzt die Zeile den
    # wiederhergestellten (engeren) Constraint.
    "UPDATE protocol SET status = 'draft' WHERE status = 'rendering'",
    "ALTER TABLE protocol DROP CONSTRAINT IF EXISTS protocol_status",
    (
        "ALTER TABLE protocol ADD CONSTRAINT protocol_status "
        "CHECK (status IN ('draft','final'))"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
