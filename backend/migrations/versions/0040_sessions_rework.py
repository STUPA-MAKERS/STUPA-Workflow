"""Sessions rework: gremium-role permissions, manager role, protokollant, generic votes

Revision ID: 0040_sessions_rework
Revises: 0039_permission_rework
Create Date: 2026-06-09 14:00:00

Sitzungs-/Protokoll-Redesign (#Sessions). Schritte (idempotent):

1. ``gremium_role.permissions`` (JSONB) — granulare Sitzungs-Berechtigungen je Rolle.
2. Pflichtrolle ``manager`` in JEDES Gremium nachziehen (NOT EXISTS).
3. Default-Permissions der Pflichtrollen setzen (vorstand/manager = alle, member =
   nur ``vote.cast``) — nur dort, wo noch leer (frische Migration).
4. ``schriftfuehrung``-Mitgliedschaften → ``manager`` desselben Gremiums umhängen,
   dann die ``schriftfuehrung``-Pflichtrolle entfernen (Protokollant ist jetzt eine
   Sitzungs-Zuweisung, keine Gremium-Rolle mehr).
5. ``meeting.protokollant_id`` (FK principal, SET NULL).
6. ``vote.application_id`` nullable (generische Beschlussfragen ohne Antrag).
7. ``vote.agenda_item_id`` (FK meeting_agenda_item, CASCADE).

``down_revision`` = ``0039_permission_rework``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_sessions_rework"
down_revision: str | None = "0039_permission_rework"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALL_PERMS = '["session.manage","vote.manage","vote.cast","protocol.write"]'
_MEMBER_PERMS = '["vote.cast"]'


def upgrade() -> None:
    # 1. permissions-Spalte
    op.add_column(
        "gremium_role",
        sa.Column(
            "permissions",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )

    # 2. Pflichtrolle ``manager`` in jedes Gremium (idempotent)
    op.execute(
        """
        INSERT INTO gremium_role (id, gremium_id, key, name_i18n, permissions)
        SELECT gen_random_uuid(), g.id, 'manager',
               '{"de": "Manager", "en": "Manager"}'::jsonb, '[]'::jsonb
        FROM gremium g
        WHERE NOT EXISTS (
            SELECT 1 FROM gremium_role r
            WHERE r.gremium_id = g.id AND r.key = 'manager'
        )
        """
    )

    # 3. Default-Permissions der Pflichtrollen (nur wo noch leer)
    for key, perms in (
        ("vorstand", _ALL_PERMS),
        ("manager", _ALL_PERMS),
        ("member", _MEMBER_PERMS),
    ):
        op.execute(
            sa.text(
                "UPDATE gremium_role SET permissions = CAST(:perms AS jsonb) "
                "WHERE key = :key AND (permissions IS NULL OR permissions = '[]'::jsonb)"
            ).bindparams(perms=perms, key=key)
        )

    # 4. schriftfuehrung-Mitgliedschaften → manager umhängen, dann Rolle löschen
    op.execute(
        """
        UPDATE gremium_membership m
        SET gremium_role_id = mgr.id
        FROM gremium_role sf
        JOIN gremium_role mgr
          ON mgr.gremium_id = sf.gremium_id AND mgr.key = 'manager'
        WHERE m.gremium_role_id = sf.id AND sf.key = 'schriftfuehrung'
        """
    )
    op.execute("DELETE FROM gremium_role WHERE key = 'schriftfuehrung'")

    # 5. meeting.protokollant_id
    op.add_column(
        "meeting",
        sa.Column("protokollant_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_meeting_protokollant",
        "meeting",
        "principal",
        ["protokollant_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 6. vote.application_id nullable
    op.alter_column(
        "vote", "application_id", existing_type=sa.Uuid(), nullable=True
    )

    # 7. vote.agenda_item_id
    op.add_column(
        "vote",
        sa.Column("agenda_item_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_vote_agenda_item",
        "vote",
        "meeting_agenda_item",
        ["agenda_item_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_vote_agenda_item", "vote", type_="foreignkey")
    op.drop_column("vote", "agenda_item_id")
    # application_id wieder NOT NULL: generische Votes (ohne Antrag) müssten zuvor weg.
    op.execute("DELETE FROM vote WHERE application_id IS NULL")
    op.alter_column(
        "vote", "application_id", existing_type=sa.Uuid(), nullable=False
    )
    op.drop_constraint("fk_meeting_protokollant", "meeting", type_="foreignkey")
    op.drop_column("meeting", "protokollant_id")
    # schriftfuehrung-Pflichtrolle best-effort wiederherstellen (Mitgliedschaften
    # bleiben beim manager — nicht eindeutig invertierbar).
    op.execute(
        """
        INSERT INTO gremium_role (id, gremium_id, key, name_i18n, permissions)
        SELECT gen_random_uuid(), g.id, 'schriftfuehrung',
               '{"de": "Schriftführung", "en": "Secretary"}'::jsonb, '[]'::jsonb
        FROM gremium g
        WHERE NOT EXISTS (
            SELECT 1 FROM gremium_role r
            WHERE r.gremium_id = g.id AND r.key = 'schriftfuehrung'
        )
        """
    )
    op.drop_column("gremium_role", "permissions")
