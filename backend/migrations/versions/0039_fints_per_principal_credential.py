"""fints_principal_creds: FinTS-Zugangsdaten je Principal trennen (#fints-percred).

Mehrere Bucher teilen sich dasselbe Bankkonto, haben aber je **eigene** Online-Banking-
Logins. Login/PIN/TAN-Methode/Client-Zustand wandern daher vom Konto in eine neue
``account_fints_credential``-Tabelle (Konto × Principal, PIN verschlüsselt). Am Konto bleibt
nur die für alle gleiche **Bank-Verbindung** (``fints_endpoint`` + ``fints_blz``). Die
TAN-Sitzung wird zusätzlich an den startenden Principal gebunden.

Das Feature war noch nicht produktiv genutzt (kein Live-Bank-Test); ein Datentransfer der
alten Konto-Spalten ist deshalb nicht nötig — sie werden schlicht entfernt. Idempotent
(``IF (NOT) EXISTS``); sauberer Down-Round-Trip.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0039_fints_principal_creds"
down_revision: str | None = "0038_gremium_membership_overlap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    # — account_fints_credential: persönliche Zugangsdaten je (Konto, Principal) —
    """
    CREATE TABLE IF NOT EXISTS account_fints_credential (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id uuid NOT NULL REFERENCES account (id) ON DELETE CASCADE,
        principal_id uuid NOT NULL REFERENCES principal (id) ON DELETE CASCADE,
        fints_login text NOT NULL,
        fints_pin_encrypted text NOT NULL,
        fints_tan_mechanism text,
        fints_state text,
        fints_last_sync_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_account_fints_credential_owner UNIQUE (account_id, principal_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_account_fints_credential_account_id "
    "ON account_fints_credential (account_id)",
    "CREATE INDEX IF NOT EXISTS ix_account_fints_credential_principal_id "
    "ON account_fints_credential (principal_id)",
    # — bank_sync_session: an den startenden Principal binden —
    # Bestehende (kurzlebige) Sitzungen sind nach dem Deploy ohnehin wertlos → leeren, dann
    # die NOT-NULL-Spalte ergänzen (kein sinnvoller Default für Altzeilen).
    "DELETE FROM bank_sync_session",
    "ALTER TABLE bank_sync_session ADD COLUMN IF NOT EXISTS principal_id uuid "
    "NOT NULL REFERENCES principal (id) ON DELETE CASCADE",
    # — account: persönliche FinTS-Spalten entfernen (nur Endpunkt + BLZ bleiben) —
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_last_sync_at",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_state",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_tan_mechanism",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_pin_encrypted",
    "ALTER TABLE account DROP COLUMN IF EXISTS fints_login",
)

_DOWNGRADE: tuple[str, ...] = (
    # account-Spalten zurück (ohne Daten — sie sind unwiederbringlich entfernt) —
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_login text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_pin_encrypted text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_tan_mechanism text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_state text",
    "ALTER TABLE account ADD COLUMN IF NOT EXISTS fints_last_sync_at timestamptz",
    "DELETE FROM bank_sync_session",
    "ALTER TABLE bank_sync_session DROP COLUMN IF EXISTS principal_id",
    "DROP TABLE IF EXISTS account_fints_credential",
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
