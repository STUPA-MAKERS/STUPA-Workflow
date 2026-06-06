"""audit: append-only-Enforcement (Trigger) + Least-Privilege-Grant (T-23)

Revision ID: 0005_audit_append_only
Revises: 0004_budget_entry_and_views
Create Date: 2026-06-06 00:00:05

``audit_entry`` selbst entsteht – wie alle Modul-Tabellen – über
``Base.metadata.create_all`` in 0002 (Single-Source-Pattern, s. ``app.models``).
Diese Revision ergänzt, was ``create_all`` nicht abbildet (security.md §4):

* **Append-only-Trigger**: ``BEFORE UPDATE OR DELETE`` (row) **und** ``BEFORE TRUNCATE``
  (statement) ⇒ ``RAISE EXCEPTION``. Der TRUNCATE-Trigger ist entscheidend: ein
  ``TRUNCATE`` umginge sonst die Row-Trigger und würde die gesamte Kette löschen
  (``verify_chain`` meldete danach fälschlich ``valid`` auf leerer Kette). Greift
  rollenunabhängig (auch für den Owner) → fail-closed, portabel, testbar. Primäre
  Durchsetzung der Unveränderlichkeit der Hash-Kette.
* **Least-Privilege-Grant**: existiert die Rolle ``audit_writer`` (deployment.md,
  ``AUDIT_DB_ROLE``), erhält sie nur ``INSERT``/``SELECT`` — UPDATE/DELETE bleiben
  entzogen. Conditional, damit Single-User-Setups (CI/Dev) ohne die Rolle laufen.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_audit_append_only"
down_revision: str | None = "0004_budget_entry_and_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_WRITER_ROLE = "audit_writer"

_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION audit_entry_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_entry is append-only; % denied', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

_GRANT = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_AUDIT_WRITER_ROLE}') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_entry FROM {_AUDIT_WRITER_ROLE};
        GRANT INSERT, SELECT ON TABLE audit_entry TO {_AUDIT_WRITER_ROLE};
    END IF;
END $$;
"""

_REVOKE = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_AUDIT_WRITER_ROLE}') THEN
        REVOKE INSERT, SELECT ON TABLE audit_entry FROM {_AUDIT_WRITER_ROLE};
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_audit_entry_no_update BEFORE UPDATE ON audit_entry "
        "FOR EACH ROW EXECUTE FUNCTION audit_entry_append_only();"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_entry_no_delete BEFORE DELETE ON audit_entry "
        "FOR EACH ROW EXECUTE FUNCTION audit_entry_append_only();"
    )
    op.execute(
        "CREATE TRIGGER trg_audit_entry_no_truncate BEFORE TRUNCATE ON audit_entry "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_entry_append_only();"
    )
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute(_REVOKE)
    op.execute("DROP TRIGGER IF EXISTS trg_audit_entry_no_truncate ON audit_entry;")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_entry_no_delete ON audit_entry;")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_entry_no_update ON audit_entry;")
    op.execute("DROP FUNCTION IF EXISTS audit_entry_append_only();")
