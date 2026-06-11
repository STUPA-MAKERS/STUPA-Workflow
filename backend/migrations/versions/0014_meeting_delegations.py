"""Sitzungsgebundene Delegationen (#delegation-rework).

Neue Tabellen ``meeting_delegation`` (Vertretung je Sitzung, Stimmrecht optional)
und ``delegation_substitute`` (Stellvertreter-Pool je Gremium); ``gremium`` erhält
``delegation_lead_minutes`` (Vorlauf-Deadline) und ``delegation_allow_external``.
Bestehende Blanko-Delegationen (``role_assignment.delegated_by``) bleiben als
Alt-Zeilen stehen, werden vom Stimmrechts-Check aber nicht mehr berücksichtigt.
Idempotent (``IF NOT EXISTS``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_meeting_delegations"
down_revision: str | None = "0013_transition_requires_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS "
        "delegation_lead_minutes integer NOT NULL DEFAULT 0"
    ),
    (
        "ALTER TABLE gremium ADD COLUMN IF NOT EXISTS "
        "delegation_allow_external boolean NOT NULL DEFAULT false"
    ),
    """
    CREATE TABLE IF NOT EXISTS meeting_delegation (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        meeting_id uuid NOT NULL REFERENCES meeting(id) ON DELETE CASCADE,
        gremium_id uuid NOT NULL REFERENCES gremium(id) ON DELETE CASCADE,
        delegator_principal_id uuid NOT NULL
            REFERENCES principal(id) ON DELETE CASCADE,
        delegate_principal_id uuid NOT NULL
            REFERENCES principal(id) ON DELETE CASCADE,
        delegate_voting boolean NOT NULL DEFAULT false,
        via_pool boolean NOT NULL DEFAULT false,
        created_by text,
        CONSTRAINT uq_meeting_delegation_delegator
            UNIQUE (meeting_id, delegator_principal_id)
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_meeting_delegation_voting_delegate "
        "ON meeting_delegation (meeting_id, delegate_principal_id) "
        "WHERE delegate_voting"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_meeting_delegation_meeting "
        "ON meeting_delegation (meeting_id)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_meeting_delegation_delegate "
        "ON meeting_delegation (delegate_principal_id)"
    ),
    """
    CREATE TABLE IF NOT EXISTS delegation_substitute (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at timestamptz NOT NULL DEFAULT now(),
        gremium_id uuid NOT NULL REFERENCES gremium(id) ON DELETE CASCADE,
        member_principal_id uuid REFERENCES principal(id) ON DELETE CASCADE,
        substitute_principal_id uuid NOT NULL
            REFERENCES principal(id) ON DELETE CASCADE,
        created_by text,
        CONSTRAINT uq_delegation_substitute
            UNIQUE (gremium_id, member_principal_id, substitute_principal_id)
    )
    """,
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_delegation_substitute_gremiumwide "
        "ON delegation_substitute (gremium_id, substitute_principal_id) "
        "WHERE member_principal_id IS NULL"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_delegation_substitute_gremium "
        "ON delegation_substitute (gremium_id)"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TABLE IF EXISTS delegation_substitute",
    "DROP TABLE IF EXISTS meeting_delegation",
    "ALTER TABLE gremium DROP COLUMN IF EXISTS delegation_allow_external",
    "ALTER TABLE gremium DROP COLUMN IF EXISTS delegation_lead_minutes",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
