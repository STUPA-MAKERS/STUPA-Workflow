"""Status lists: the statuses of the Bestellungen and Events become admin config.

The upgrade creates the table ``status_def`` (F/administration/admin/003035) and fills
the list of the Bestellungen with the four statuses of today and the list of the Events
with its three start statuses (003039). It drops the check of ``purchase_order.status``,
because the admin now names the statuses, and the column has no default any more,
because the start status is the one that the list names. A stored Bestellung keeps its
status, because each old status is a key of the new list. Each list gets its first
config revision, so the audit log can revert the first save of the admin. The
revisions are append-only, so the downgrade keeps them. The upgrade grants
``admin.order_phases`` and ``admin.event_phases`` to the ``admin``
role. The step is idempotent.

Revision ID: 5d8c2a7e41f3
Revises: 9f288998cf57
Create Date: 2026-11-25 19:30:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "5d8c2a7e41f3"
down_revision: str | None = "9f288998cf57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: kind, key, position, de, en, tone, phase, start, date
_SEED: tuple[tuple[str, str, int, str, str, str, str, bool, str | None], ...] = (
    ("order", "planned", 0, "Geplant", "Planned", "neutral", "open", True, None),
    ("order", "ordered", 1, "Bestellt", "Ordered", "warn", "open", False, "orderedOn"),
    ("order", "delivered", 2, "Geliefert", "Delivered", "accent", "done", False, "deliveredOn"),
    ("order", "cancelled", 3, "Storniert", "Cancelled", "muted", "void", False, None),
    ("event", "planned", 0, "Geplant", "Planned", "neutral", "open", True, None),
    ("event", "settled", 1, "Abgerechnet", "Settled", "accent", "done", False, None),
    ("event", "cancelled", 2, "Abgesagt", "Cancelled", "muted", "void", False, None),
)


def _seed_row(row: tuple[str, str, int, str, str, str, str, bool, str | None]) -> str:
    """Render one seed status as the values of an insert."""
    kind, key, position, de, en, tone, phase, start, sets_date = row
    date_sql = f"'{sets_date}'" if sets_date else "NULL"
    name = json.dumps({"de": de, "en": en})
    start_sql = "true" if start else "false"
    return (
        f"(gen_random_uuid(), '{kind}', '{key}', {position}, '{name}'::jsonb, "
        f"'{tone}', '{phase}', {start_sql}, {date_sql})"
    )


_UPGRADE: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS status_def (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        list_kind text NOT NULL,
        key text NOT NULL,
        position integer NOT NULL,
        name jsonb NOT NULL DEFAULT '{}'::jsonb,
        tone text NOT NULL DEFAULT 'neutral',
        phase text NOT NULL,
        is_start boolean NOT NULL DEFAULT false,
        sets_date text,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_status_def_list_key UNIQUE (list_kind, key),
        CONSTRAINT uq_status_def_list_position UNIQUE (list_kind, position),
        CONSTRAINT ck_status_def_list_kind CHECK (list_kind IN ('order', 'event')),
        CONSTRAINT ck_status_def_phase CHECK (phase IN ('open', 'done', 'void')),
        CONSTRAINT ck_status_def_tone
            CHECK (tone IN ('neutral', 'accent', 'warn', 'error', 'muted')),
        CONSTRAINT ck_status_def_sets_date CHECK (
            sets_date IS NULL
            OR (list_kind = 'order' AND sets_date IN ('orderedOn', 'deliveredOn'))
        ),
        CONSTRAINT ck_status_def_position CHECK (position >= 0),
        CONSTRAINT ck_status_def_start_open CHECK (NOT is_start OR phase = 'open')
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_status_def_start ON status_def (list_kind) "
    "WHERE is_start",
    "INSERT INTO status_def "
    "(id, list_kind, key, position, name, tone, phase, is_start, sets_date) VALUES "
    + ", ".join(_seed_row(row) for row in _SEED)
    + " ON CONFLICT DO NOTHING",
    (
        "INSERT INTO config_revision (entity_type, entity_id, version, snapshot) "
        "SELECT 'status_list', list_kind, 1, jsonb_build_object('statuses', jsonb_agg("
        "jsonb_build_object('key', key, 'name', name, 'tone', tone, 'phase', phase, "
        "'start', is_start, 'setsDate', sets_date) ORDER BY position)) "
        "FROM status_def GROUP BY list_kind "
        "ON CONFLICT DO NOTHING"
    ),
    "ALTER TABLE purchase_order DROP CONSTRAINT IF EXISTS ck_purchase_order_status",
    "ALTER TABLE purchase_order ALTER COLUMN status DROP DEFAULT",
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT r.id, p.permission FROM role r "
        "CROSS JOIN (VALUES ('admin.order_phases'), ('admin.event_phases')) AS p(permission) "
        "WHERE r.key = 'admin' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission "
    "WHERE permission IN ('admin.order_phases', 'admin.event_phases')",
    "UPDATE purchase_order SET status = 'planned' "
    "WHERE status NOT IN ('planned', 'ordered', 'delivered', 'cancelled')",
    "ALTER TABLE purchase_order ALTER COLUMN status SET DEFAULT 'planned'",
    "ALTER TABLE purchase_order ADD CONSTRAINT ck_purchase_order_status "
    "CHECK (status IN ('planned', 'ordered', 'delivered', 'cancelled'))",
    "DROP TABLE IF EXISTS status_def",
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema from this revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
