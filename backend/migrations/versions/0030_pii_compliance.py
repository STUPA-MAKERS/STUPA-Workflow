"""DSGVO/PII-Compliance: Anonymisierung, Löschanträge, Aufbewahrung, Auskunft.

* Re-add ``applicant.anonymized_at`` + ``form_field.is_pii`` (in 0015 entfernt,
  hier mit echtem Endpoint/Cron/UI wieder eingeführt — Branch ``feat/PII-Re-Add``).
* ``application_type.retention_months`` — Aufbewahrungsfrist je Typ
  (NULL = globaler Default aus ``privacy_settings``).
* ``state.is_terminal`` — Endzustand (terminale Anträge sind aufbewahrungs-/
  anonymisierungs-fähig, flows §).
* ``privacy_settings`` — Single-Row (id=1): ``default_retention_months``
  (Default 24, DSB-Platzhalter; admin-gepflegt über ``/admin/privacy``).
* ``erasure_request`` — Löschantrags-Queue (DSGVO Art. 17): Selbstauskunft per
  Magic-Link bzw. Admin-Anlage; ``status`` open/executed/rejected.
* Neue Permission ``privacy.manage``: an alle Rollen verteilt, die ``admin.site``
  halten (Bereichs-Logik wie Migration 0016/0018).

Idempotent (``IF [NOT] EXISTS`` / ``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030_pii_compliance"
down_revision: str | None = "0029_meeting_end_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    # --- 0015 invertieren: PII-Spalten wieder anlegen -----------------------
    "ALTER TABLE applicant ADD COLUMN IF NOT EXISTS anonymized_at timestamptz",
    (
        "ALTER TABLE form_field ADD COLUMN IF NOT EXISTS "
        "is_pii boolean NOT NULL DEFAULT false"
    ),
    # --- Aufbewahrungs-/Terminal-Metadaten ----------------------------------
    (
        "ALTER TABLE application_type ADD COLUMN IF NOT EXISTS "
        "retention_months integer"
    ),
    (
        "ALTER TABLE state ADD COLUMN IF NOT EXISTS "
        "is_terminal boolean NOT NULL DEFAULT false"
    ),
    # --- Plattform-Privacy-Config (Single-Row) ------------------------------
    (
        "CREATE TABLE IF NOT EXISTS privacy_settings ("
        "id integer PRIMARY KEY DEFAULT 1, "
        "default_retention_months integer NOT NULL DEFAULT 24, "
        "CONSTRAINT privacy_settings_singleton CHECK (id = 1), "
        "CONSTRAINT default_retention_months_min "
        "CHECK (default_retention_months >= 1))"
    ),
    "INSERT INTO privacy_settings (id) VALUES (1) ON CONFLICT DO NOTHING",
    # --- Löschantrags-Queue (DSGVO Art. 17) ---------------------------------
    (
        "CREATE TABLE IF NOT EXISTS erasure_request ("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "created_at timestamptz NOT NULL DEFAULT now(), "
        "subject_type text NOT NULL, "
        "application_id uuid REFERENCES application(id) ON DELETE SET NULL, "
        "principal_id uuid REFERENCES principal(id) ON DELETE SET NULL, "
        "email citext, "
        "status text NOT NULL DEFAULT 'open', "
        "requested_by text, "
        "handled_by text, "
        "handled_at timestamptz, "
        "reason text, "
        "CONSTRAINT erasure_request_subject_type "
        "CHECK (subject_type IN ('applicant','principal')), "
        "CONSTRAINT erasure_request_status "
        "CHECK (status IN ('open','executed','rejected')))"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_erasure_request_status "
        "ON erasure_request (status)"
    ),
    # --- Permission an admin.site-Rollen verteilen --------------------------
    (
        "INSERT INTO role_permission (role_id, permission) "
        "SELECT role_id, 'privacy.manage' FROM role_permission "
        "WHERE permission = 'admin.site' "
        "ON CONFLICT DO NOTHING"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DELETE FROM role_permission WHERE permission = 'privacy.manage'",
    "DROP TABLE IF EXISTS erasure_request",
    "DROP TABLE IF EXISTS privacy_settings",
    "ALTER TABLE state DROP COLUMN IF EXISTS is_terminal",
    "ALTER TABLE application_type DROP COLUMN IF EXISTS retention_months",
    "ALTER TABLE form_field DROP COLUMN IF EXISTS is_pii",
    "ALTER TABLE applicant DROP COLUMN IF EXISTS anonymized_at",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
