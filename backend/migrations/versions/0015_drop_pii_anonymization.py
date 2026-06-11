"""PII-/Anonymisierungs-Feature entfernt (Backlog #3).

Die Feature-Reste (``applicant.anonymized_at``, ``form_field.is_pii``) stammen
aus dem lange verworfenen Anonymisierungs-Konzept: es gab weder einen Endpoint
noch UI; die Audit-Actions ``pii_access``/``pii_deletion``/``anonymization``
wurden nie geschrieben. Bestehende ``audit_entry``-Zeilen bleiben unberührt
(append-only). Idempotent (``IF [NOT] EXISTS``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_drop_pii_anonymization"
down_revision: str | None = "0014_meeting_delegations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    "ALTER TABLE applicant DROP COLUMN IF EXISTS anonymized_at",
    "ALTER TABLE form_field DROP COLUMN IF EXISTS is_pii",
)

_DOWNGRADE: tuple[str, ...] = (
    (
        "ALTER TABLE applicant ADD COLUMN IF NOT EXISTS "
        "anonymized_at timestamptz"
    ),
    (
        "ALTER TABLE form_field ADD COLUMN IF NOT EXISTS "
        "is_pii boolean NOT NULL DEFAULT false"
    ),
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
