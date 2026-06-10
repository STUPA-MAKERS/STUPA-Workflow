"""Application: ``email_confirmed_at`` (Gast-Einreichung muss bestätigt werden).

Eine von einem nicht angemeldeten Nutzer eingereichte Antragstellung ist erst
**sichtbar**, nachdem die E-Mail per Magic-Link bestätigt wurde; unbestätigt wird
sie nach 12 h verworfen. Bestandsanträge gelten als bestätigt → Backfill auf
``created_at`` (sonst würden sie unsichtbar). Neue Gast-Anträge starten mit NULL.
Idempotent (``IF NOT EXISTS``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_application_email_confirmed"
down_revision: str | None = "0009_transition_color"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE application ADD COLUMN IF NOT EXISTS email_confirmed_at timestamptz",
    # Bestandsanträge als bestätigt behandeln, damit sie nicht plötzlich verschwinden.
    "UPDATE application SET email_confirmed_at = created_at WHERE email_confirmed_at IS NULL",
)

_DOWNGRADE: tuple[str, ...] = (
    "ALTER TABLE application DROP COLUMN IF EXISTS email_confirmed_at",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
