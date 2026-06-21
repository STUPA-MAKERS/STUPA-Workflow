"""applicant_session: serverseitige Magic-Link-Sessions (security.md §1).

Macht den Antragsteller-(Magic-Link-)Token **zustandsbehaftet**, analog zu
``auth_session``: der Browser hält nur eine signierte, opake ``sid``; ``application_id``
und ``scope`` liegen serverseitig. Damit ist ein Token nicht mehr allein aus
``SESSION_SECRET`` fälschbar (er braucht eine existierende Zeile) und serverseitig
widerrufbar (Logout = Zeile gelöscht, Kill-Switch = ``revoked_at`` gesetzt, z. B. bei
Anonymisierung).

Idempotent (``IF NOT EXISTS``); sauberer Down-Round-Trip. Auf einem frischen Schema
entsteht die Tabelle ohnehin über ``Base.metadata.create_all`` (0001/0002).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0037_applicant_session"
down_revision: str | None = "0036_drop_fully_bound"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS applicant_session (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        sid text NOT NULL UNIQUE,
        application_id uuid NOT NULL REFERENCES application (id) ON DELETE CASCADE,
        scope text NOT NULL,
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_applicant_session_application_id "
    "ON applicant_session (application_id)",
)

_DOWNGRADE: tuple[str, ...] = ("DROP TABLE IF EXISTS applicant_session",)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
