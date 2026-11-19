"""Decisions outside the platform, approved amounts and forced-status reasons.

The upgrade does four things:

1. It adds the columns ``forced``, ``force_reason`` and ``outside_decision`` to
   ``status_event`` and the columns ``amend_reason``, ``previous_amount``,
   ``basis_date`` and ``basis_gremium_id`` to ``application_decision``. Idempotent,
   because a fresh database gets them from the ``create_all`` baseline (0001).
2. It marks the old forced status events as ``forced``. The audit log is the only
   record of a forced change before this revision: its ``status_change`` entry holds
   ``forced: true`` and the id of the status event.
3. It gives ``application.record_decision`` (spec 001603) and
   ``application.amend_decision`` (spec 001620) to the roles ``finanzreferent`` and
   ``haushaltsbeauftragte`` when these roles exist, and to ``admin``, which holds
   every permission.
4. It gives each approved application without an approved amount the requested
   amount (spec 001613). An application without a valid decision gets a new decision
   without conditions. A valid decision without an amount gives way to a new decision
   that keeps its conditions, because nobody edits a decision row. The backfill
   writes no audit entry, because only the application writes the audit chain.

The downgrade drops the columns and the two permissions. The backfilled decisions
stay, because they are valid decisions.

Revision ID: c5e19a7d3b42
Revises: a4c71e2b9d05
Create Date: 2026-11-19 23:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c5e19a7d3b42"
down_revision: str | None = "a4c71e2b9d05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "ALTER TABLE status_event ADD COLUMN IF NOT EXISTS forced boolean NOT NULL DEFAULT false",
    "ALTER TABLE status_event ADD COLUMN IF NOT EXISTS force_reason text",
    "ALTER TABLE status_event ADD COLUMN IF NOT EXISTS outside_decision jsonb",
    "ALTER TABLE application_decision ADD COLUMN IF NOT EXISTS amend_reason text",
    "ALTER TABLE application_decision ADD COLUMN IF NOT EXISTS previous_amount numeric(12, 2)",
    "ALTER TABLE application_decision ADD COLUMN IF NOT EXISTS basis_date date",
    "ALTER TABLE application_decision ADD COLUMN IF NOT EXISTS basis_gremium_id uuid",
)

_MARK_FORCED = """
UPDATE status_event SET forced = true
WHERE id IN (
    SELECT (data->>'statusEventId')::uuid FROM audit_entry
    WHERE action = 'status_change'
      AND data->>'forced' = 'true'
      AND data->>'statusEventId' IS NOT NULL
)
"""

_GRANT = """
INSERT INTO role_permission (role_id, permission)
SELECT r.id, p.permission FROM role r
CROSS JOIN (VALUES ('application.record_decision'), ('application.amend_decision'))
    AS p(permission)
WHERE r.key IN ('finanzreferent', 'haushaltsbeauftragte', 'admin')
ON CONFLICT DO NOTHING
"""

_APPROVED_WITHOUT_AMOUNT = """
SELECT a.id FROM application a
JOIN state s ON s.id = a.current_state_id
WHERE s.is_approved AND a.approved_amount IS NULL AND a.amount IS NOT NULL
"""

_BACKFILL = (
    f"""
    CREATE TEMP TABLE backfill_app ON COMMIT DROP AS {_APPROVED_WITHOUT_AMOUNT}
    """,
    """
    CREATE TEMP TABLE backfill_old ON COMMIT DROP AS
    SELECT d.id, d.application_id, d.conditions FROM application_decision d
    JOIN backfill_app b ON b.id = d.application_id
    WHERE d.superseded_at IS NULL
    """,
    """
    UPDATE application_decision SET superseded_at = now()
    WHERE id IN (SELECT id FROM backfill_old)
    """,
    """
    INSERT INTO application_decision
        (id, application_id, approved_amount, conditions, decided_at)
    SELECT gen_random_uuid(), a.id, a.amount, COALESCE(o.conditions, '[]'::jsonb), now()
    FROM application a
    JOIN backfill_app b ON b.id = a.id
    LEFT JOIN backfill_old o ON o.application_id = a.id
    """,
    """
    UPDATE application SET approved_amount = amount
    WHERE id IN (SELECT id FROM backfill_app)
    """,
)


def upgrade() -> None:
    """Add the columns, mark the old forced events, grant and backfill."""
    for statement in _COLUMNS:
        op.execute(statement)
    op.execute(_MARK_FORCED)
    op.execute(_GRANT)
    for statement in _BACKFILL:
        op.execute(statement)


def downgrade() -> None:
    """Drop the columns and the two permissions."""
    op.execute(
        "DELETE FROM role_permission WHERE permission IN "
        "('application.record_decision', 'application.amend_decision')"
    )
    for table, column in (
        ("status_event", "forced"),
        ("status_event", "force_reason"),
        ("status_event", "outside_decision"),
        ("application_decision", "amend_reason"),
        ("application_decision", "previous_amount"),
        ("application_decision", "basis_date"),
        ("application_decision", "basis_gremium_id"),
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
