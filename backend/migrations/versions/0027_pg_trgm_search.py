"""Fuzzy-Suche (#3/#4): ``pg_trgm``-Extension + GIN-Trigram-Indizes.

Server-seitige Fuzzy-Suche (Buchungen, Anträge, Rechnungen, Sitzungen) nutzt
``pg_trgm``-Ähnlichkeit zum Filtern **und** Ranken. Diese Migration legt die
Extension + je einen GIN-Trigram-Index (``gin_trgm_ops``) auf **jede** Spalte an,
die eine Suche tatsächlich anfasst — sonst fiele ``similarity()`` auf einen
Seq-Scan zurück.

Anträge durchsuchen »sinnvollen Text« (Titel + Text-Antwortwerte), nicht den
ganzen JSON-Blob. Dafür legt die Migration die **IMMUTABLE** SQL-Funktion
``app_search_text(jsonb)`` an (Konkatenation aller String-Skalare des ``data``-
JSONB, inkl. ``title``; Zahlen/Bools/Keys bleiben außen vor) und indiziert deren
Ausdruck per GIN-Trigram. Der Such-Service ruft dieselbe Funktion auf.

``CREATE EXTENSION pg_trgm`` braucht ``CREATE`` auf der DB (Superuser/Owner) beim
Deploy. Kann die Managed-Rolle das nicht, die Extension vorab vom DB-Admin anlegen
lassen (``CREATE EXTENSION IF NOT EXISTS pg_trgm``) — dann ist diese Anweisung ein
No-Op. Alle Anweisungen sind idempotent (``IF NOT EXISTS``).

Round-Trip-getestet (``test_migrations``): die Extension bleibt beim Downgrade
bestehen (andere Objekte könnten sie nutzen), nur Indizes + Funktion fallen weg.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_pg_trgm_search"
down_revision: str | None = "0026_per_page_admin_perms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE: tuple[str, ...] = (
    # Trigram-Suche/-Ranking (similarity, % , gin_trgm_ops). Braucht CREATE auf der
    # DB beim Deploy — ggf. vorab vom DB-Admin anlegen lassen (dann hier No-Op).
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # Antrags-Suchtext: SINNVOLLER Text aus dem JSONB (Titel + Text-Antworten),
    # konkateniert. IMMUTABLE → in einem Ausdrucks-Index verwendbar.
    # ``jsonb_path_query_array`` zieht rekursiv alle String-Skalare; gefiltert wird
    # auf Werte, die mindestens EINEN Buchstaben tragen (``~ '[[:alpha:]]'``) — so
    # fallen als String gespeicherte Beträge/Daten/Zahlen (z. B. Währungsfelder
    # ``"1234.00"``) sowie reine ids/Enums-Codes raus; nur lesbarer Text bleibt.
    (
        "CREATE OR REPLACE FUNCTION app_search_text(data jsonb) RETURNS text AS $$"
        " SELECT coalesce("
        "   array_to_string("
        "     ARRAY("
        "       SELECT v FROM jsonb_array_elements_text("
        "         jsonb_path_query_array(data, '$.** ? (@.type() == \"string\")')"
        "       ) AS v"
        "       WHERE v ~ '[[:alpha:]]'"
        "     ),"
        "     ' '"
        "   ),"
        "   ''"
        " )"
        " $$ LANGUAGE sql IMMUTABLE"
    ),
    # --- GIN-Trigram-Indizes je durchsuchter Spalte ---------------------------
    # Buchungen (budget_expense): Freitext-Felder der Buchungssuche (#3).
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_budget_expense_description "
        "ON budget_expense USING gin (description gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_budget_expense_correspondent "
        "ON budget_expense USING gin (correspondent gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_budget_expense_reference_number "
        "ON budget_expense USING gin (reference_number gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_budget_expense_category "
        "ON budget_expense USING gin (category gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_budget_expense_note "
        "ON budget_expense USING gin (note gin_trgm_ops)"
    ),
    # Rechnungen (invoice): Nummer + Lieferant (+ Notiz mitgesucht).
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_invoice_number "
        "ON invoice USING gin (number gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_invoice_supplier "
        "ON invoice USING gin (supplier gin_trgm_ops)"
    ),
    ("CREATE INDEX IF NOT EXISTS ix_trgm_invoice_note ON invoice USING gin (note gin_trgm_ops)"),
    # Konto (account): Name (Buchungssuche joint Account.name mit).
    ("CREATE INDEX IF NOT EXISTS ix_trgm_account_name ON account USING gin (name gin_trgm_ops)"),
    # Sitzungen (meeting): Titel (Timeline-Suche, #4).
    ("CREATE INDEX IF NOT EXISTS ix_trgm_meeting_title ON meeting USING gin (title gin_trgm_ops)"),
    # Gremium-Name + Protokollant-Anzeigename (Sitzungssuche joint beide mit).
    ("CREATE INDEX IF NOT EXISTS ix_trgm_gremium_name ON gremium USING gin (name gin_trgm_ops)"),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_principal_display_name "
        "ON principal USING gin (display_name gin_trgm_ops)"
    ),
    # Anträge (application): Suchtext-Ausdruck (Titel + Text-Antworten).
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_application_search_text "
        "ON application USING gin (app_search_text(data) gin_trgm_ops)"
    ),
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_trgm_application_search_text",
    "DROP INDEX IF EXISTS ix_trgm_principal_display_name",
    "DROP INDEX IF EXISTS ix_trgm_gremium_name",
    "DROP INDEX IF EXISTS ix_trgm_meeting_title",
    "DROP INDEX IF EXISTS ix_trgm_account_name",
    "DROP INDEX IF EXISTS ix_trgm_invoice_note",
    "DROP INDEX IF EXISTS ix_trgm_invoice_supplier",
    "DROP INDEX IF EXISTS ix_trgm_invoice_number",
    "DROP INDEX IF EXISTS ix_trgm_budget_expense_note",
    "DROP INDEX IF EXISTS ix_trgm_budget_expense_category",
    "DROP INDEX IF EXISTS ix_trgm_budget_expense_reference_number",
    "DROP INDEX IF EXISTS ix_trgm_budget_expense_correspondent",
    "DROP INDEX IF EXISTS ix_trgm_budget_expense_description",
    "DROP FUNCTION IF EXISTS app_search_text(jsonb)",
    # Extension bleibt bewusst bestehen (andere Objekte könnten sie nutzen).
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
