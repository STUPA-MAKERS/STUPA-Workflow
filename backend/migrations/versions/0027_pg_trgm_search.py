"""Fuzzy search: the `pg_trgm` extension and GIN trigram indexes.

The server-side fuzzy search over bookings, applications, invoices and meetings
uses `pg_trgm` similarity to **filter** and to **rank**. This migration creates
the extension and one GIN trigram index (`gin_trgm_ops`) on **every** column
that a search really touches. Without such an index, `similarity()` falls back
to a sequential scan.

The application search reads meaningful text only: the title and the text
answer values, not the whole JSON blob. For that, this migration creates the
**IMMUTABLE** SQL function `app_search_text(jsonb)`. The function concatenates
every string scalar of the `data` JSONB, including `title`, and leaves numbers,
booleans and keys out. A GIN trigram index covers that expression. The search
service calls the same function.

`CREATE EXTENSION pg_trgm` needs `CREATE` on the database at deploy time, so the
role must be the superuser or the owner. If the managed role cannot do this, ask
the database admin to create the extension first
(`CREATE EXTENSION IF NOT EXISTS pg_trgm`). This statement is then a no-op.
All statements are idempotent (`IF NOT EXISTS`).

`test_migrations` covers the round trip. The downgrade keeps the extension,
because other objects can use it. It drops the indexes and the function only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_pg_trgm_search"
down_revision: str | None = "0026_per_page_admin_perms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The extension needs CREATE on the database at deploy time; a pre-created one makes
#: the statement a no-op. ``app_search_text`` joins the meaningful text of the JSONB
#: (title and text answers) and is IMMUTABLE, so an expression index can use it.
#: ``jsonb_path_query_array`` pulls every string scalar recursively, and the filter
#: ``~ '[[:alpha:]]'`` keeps only values with at least one letter, so amounts, dates,
#: numbers stored as strings (a currency value such as "1234.00"), ids and enum codes
#: drop out. The indexes cover the free-text fields of the booking search, the account
#: name it joins, the meeting title of the timeline search, and the Gremium and writer
#: names that the meeting search joins.
_UPGRADE: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
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
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_invoice_number "
        "ON invoice USING gin (number gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_invoice_supplier "
        "ON invoice USING gin (supplier gin_trgm_ops)"
    ),
    ("CREATE INDEX IF NOT EXISTS ix_trgm_invoice_note ON invoice USING gin (note gin_trgm_ops)"),
    ("CREATE INDEX IF NOT EXISTS ix_trgm_account_name ON account USING gin (name gin_trgm_ops)"),
    ("CREATE INDEX IF NOT EXISTS ix_trgm_meeting_title ON meeting USING gin (title gin_trgm_ops)"),
    ("CREATE INDEX IF NOT EXISTS ix_trgm_gremium_name ON gremium USING gin (name gin_trgm_ops)"),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_principal_display_name "
        "ON principal USING gin (display_name gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS ix_trgm_application_search_text "
        "ON application USING gin (app_search_text(data) gin_trgm_ops)"
    ),
)

#: The extension stays, because other objects can use it.
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
)


def upgrade() -> None:
    """Upgrade the schema to this revision."""
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade the schema to the previous revision."""
    for stmt in _DOWNGRADE:
        op.execute(stmt)
