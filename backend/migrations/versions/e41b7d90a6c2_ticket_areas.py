"""Tickets: the Bereiche, their Kategorien and the gremium permission ``ticket.work``.

The upgrade:

1. creates ``ticket_area`` and ``ticket_category``.
2. creates the built-in Bereich ``Plattform`` with its fixed id. Its switch
   ``notify_new`` takes the value of ``tickets.notifyNew`` of the active site
   configuration, because that setting belongs to the Bereich from now on.
3. adds ``ticket.area_id`` and ``ticket.category_id`` and puts each existing ticket into
   ``Plattform``, so the holders of ``ticket.manage`` find each ticket as before.
4. lets ``ticket.kind`` be NULL, because only a ticket of ``Plattform`` has a kind.
5. widens the check of the event kinds by ``category`` and ``area``.
6. adds ``ticket.work`` to the forced roles ``vorstand`` and ``manager`` of every
   Gremium, because a new forced permission reaches only new Gremien through the role
   catalog.

All steps are idempotent. A fresh database already gets the tables and the columns from
the ``create_all`` baseline (0001), because the models sit in ``app.models``.

The downgrade deletes the tickets of every Bereich other than ``Plattform``, because the
older schema has no place for them, and removes the columns, the tables and the
permission.

Revision ID: e41b7d90a6c2
Revises: c7a94e12d5b3
Create Date: 2026-11-23 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e41b7d90a6c2"
down_revision: str | None = "c7a94e12d5b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLATFORM = "7a11e700-0000-4000-8000-000000000001"
_EVENT_KINDS = "'created', 'status', 'assignee', 'kind', 'todo_done'"

_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS ticket_area (
        id uuid CONSTRAINT pk_ticket_area PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL,
        gremium_id uuid CONSTRAINT fk_ticket_area_gremium_id_gremium
            REFERENCES gremium (id) ON DELETE SET NULL,
        platform boolean NOT NULL DEFAULT false,
        notify_new boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_ticket_area_name UNIQUE (name),
        CONSTRAINT ck_ticket_area_platform_without_gremium
            CHECK (NOT platform OR gremium_id IS NULL)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_area_one_platform "
    "ON ticket_area (platform) WHERE platform",
    "CREATE INDEX IF NOT EXISTS ix_ticket_area_gremium_id ON ticket_area (gremium_id)",
    """
    CREATE TABLE IF NOT EXISTS ticket_category (
        id uuid CONSTRAINT pk_ticket_category PRIMARY KEY DEFAULT gen_random_uuid(),
        area_id uuid NOT NULL CONSTRAINT fk_ticket_category_area_id_ticket_area
            REFERENCES ticket_area (id) ON DELETE CASCADE,
        name text NOT NULL,
        position integer NOT NULL DEFAULT 0,
        CONSTRAINT uq_ticket_category_area_name UNIQUE (area_id, name)
            DEFERRABLE INITIALLY DEFERRED
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_ticket_category_area_id ON ticket_category (area_id)",
    f"""
    INSERT INTO ticket_area (id, name, platform, notify_new)
    SELECT '{_PLATFORM}', 'Plattform', true,
           COALESCE(
               (SELECT (branding -> 'tickets' ->> 'notifyNew')::boolean
                FROM site_config_version WHERE active),
               true
           )
    WHERE NOT EXISTS (SELECT 1 FROM ticket_area WHERE platform)
    """,
    "ALTER TABLE ticket ADD COLUMN IF NOT EXISTS area_id uuid",
    "ALTER TABLE ticket ADD COLUMN IF NOT EXISTS category_id uuid",
    f"UPDATE ticket SET area_id = '{_PLATFORM}' WHERE area_id IS NULL",
    "ALTER TABLE ticket ALTER COLUMN area_id SET NOT NULL",
    "ALTER TABLE ticket DROP CONSTRAINT IF EXISTS fk_ticket_area_id_ticket_area",
    "ALTER TABLE ticket ADD CONSTRAINT fk_ticket_area_id_ticket_area "
    "FOREIGN KEY (area_id) REFERENCES ticket_area (id)",
    "ALTER TABLE ticket DROP CONSTRAINT IF EXISTS fk_ticket_category_id_ticket_category",
    "ALTER TABLE ticket ADD CONSTRAINT fk_ticket_category_id_ticket_category "
    "FOREIGN KEY (category_id) REFERENCES ticket_category (id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_ticket_area_id ON ticket (area_id)",
    "ALTER TABLE ticket ALTER COLUMN kind DROP NOT NULL",
    "ALTER TABLE ticket_event DROP CONSTRAINT IF EXISTS ck_ticket_event_kind",
    "ALTER TABLE ticket_event ADD CONSTRAINT ck_ticket_event_kind "
    f"CHECK (kind IN ({_EVENT_KINDS}, 'category', 'area'))",
    "UPDATE gremium_role SET permissions = permissions || '[\"ticket.work\"]'::jsonb "
    "WHERE key IN ('vorstand', 'manager') AND NOT permissions ? 'ticket.work'",
)

_DOWNGRADE: tuple[str, ...] = (
    "UPDATE gremium_role SET permissions = permissions - 'ticket.work' "
    "WHERE permissions ? 'ticket.work'",
    "DELETE FROM ticket_event WHERE kind IN ('category', 'area')",
    "ALTER TABLE ticket_event DROP CONSTRAINT IF EXISTS ck_ticket_event_kind",
    f"ALTER TABLE ticket_event ADD CONSTRAINT ck_ticket_event_kind CHECK (kind IN ({_EVENT_KINDS}))",
    f"DELETE FROM ticket WHERE area_id <> '{_PLATFORM}' OR kind IS NULL",
    "ALTER TABLE ticket ALTER COLUMN kind SET NOT NULL",
    "DROP INDEX IF EXISTS ix_ticket_area_id",
    "ALTER TABLE ticket DROP COLUMN IF EXISTS category_id",
    "ALTER TABLE ticket DROP COLUMN IF EXISTS area_id",
    "DROP TABLE IF EXISTS ticket_category",
    "DROP TABLE IF EXISTS ticket_area",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
