"""Vote: Status ``cancelled`` (Wahl abbrechen via manueller Transition, #abort-vote).

Verlässt ein Antrag seinen ``vote``-State über eine **manuelle** Transition
(z. B. »Wahl abbrechen«), werden seine offenen Abstimmungen storniert statt
für immer offen zu hängen (``close`` fände keinen Branch mehr → 409). Der
CheckConstraint ``vote_status`` muss den neuen Endzustand erlauben.
Idempotent (DROP IF EXISTS + Neuanlage).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_vote_cancelled_status"
down_revision: str | None = "0011_protocol_rendering_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS vote_status",
    (
        "ALTER TABLE vote ADD CONSTRAINT vote_status "
        "CHECK (status IN ('draft','open','closed','cancelled'))"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    # Stornierte Votes als geschlossen (ohne Ergebnis) behandeln, sonst verletzt
    # die Zeile den wiederhergestellten (engeren) Constraint.
    "UPDATE vote SET status = 'closed' WHERE status = 'cancelled'",
    "ALTER TABLE vote DROP CONSTRAINT IF EXISTS vote_status",
    (
        "ALTER TABLE vote ADD CONSTRAINT vote_status "
        "CHECK (status IN ('draft','open','closed'))"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
