"""Fuzzy search (#3/#4): the `pg_trgm` extension and GIN trigram indexes.

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


_UPGRADE: tuple[str, ...] = (
    # Needs CREATE on the database at deploy time. A pre-created extension makes
    # this statement a no-op.
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # Application search text: the MEANINGFUL text of the JSONB (title plus text
    # answers), concatenated. IMMUTABLE, so an expression index can use it.
    # `jsonb_path_query_array` pulls every string scalar recursively. The filter
    # `~ '[[:alpha:]]'` keeps only values that carry at least ONE letter. Amounts,
    # dates and numbers stored as strings (a currency field such as "1234.00") and
    # plain ids or enum codes drop out. Only readable text stays.
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
    # The free-text fields of the booking search (#3).
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
    # Account: the booking search joins Account.name.
    ("CREATE INDEX IF NOT EXISTS ix_trgm_account_name ON account USING gin (name gin_trgm_ops)"),
    # The meeting title, for the timeline search (#4).
    ("CREATE INDEX IF NOT EXISTS ix_trgm_meeting_title ON meeting USING gin (title gin_trgm_ops)"),
    # The meeting search joins the Gremium name and the protocol writer name.
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
    # The extension stays on purpose. Other objects can use it.
)


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE:
        op.execute(stmt)
