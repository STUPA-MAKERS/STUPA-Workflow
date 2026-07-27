"""Remove the PII and anonymization feature (backlog #3).

`applicant.anonymized_at` and `form_field.is_pii` are the last parts of an
anonymization concept that the project dropped long ago. Neither an endpoint nor
a user interface ever used them. The audit actions `pii_access`, `pii_deletion`
and `anonymization` never reached the log. Existing `audit_entry` rows stay
untouched, because the audit log is append-only. The migration is idempotent
(`IF [NOT] EXISTS`).
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
