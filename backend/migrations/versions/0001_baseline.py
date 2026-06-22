"""baseline: extensions + full schema (create_all) + raw DDL (T-06, squashed)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-10 00:00:01

Pre-Alpha-Squash (#initialdata): die zuvor ~48 inkrementellen Revisionen sind zu
**zwei** Migrationen verdichtet — diesem Schema-Baseline und ``0002_seed`` (Daten).
Es gibt keine Bestands-DBs (alles zurückgesetzt), daher ist ein sauberer Neustart
gefahrlos und beseitigt die kaputte Up/Down-Kette (doppelte Spalten aus
create_all-dann-ALTER).

Single-Source: das **gesamte** Schema entsteht aus ``app.db.Base.metadata`` (via
``app.models`` befüllt) → Modelle und Migration sind garantiert deckungsgleich.
Ergänzt wird nur, was ``create_all`` nicht abbildet (security.md §4 / data-model §3):

* **Extensions** ``pgcrypto`` (``gen_random_uuid()``) + ``citext`` (case-insensitive
  E-Mail) — vor ``create_all``, da Spalten-Defaults/Typen sie brauchen.
* **Audit-Append-only**: ``BEFORE UPDATE/DELETE`` (row) + ``BEFORE TRUNCATE``
  (statement) ⇒ ``RAISE EXCEPTION``; Least-Privilege-Grant an ``audit_writer``.
* **Materialized Views** ``mv_budget_usage`` (Topf×Stufe), ``mv_status_distribution``
  (Gremium×State), ``mv_budget_rollup`` (gebundene Summe je Knoten×HHJ) — je mit
  Unique-Index für ``REFRESH … CONCURRENTLY`` (Worker).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401  — befüllt Base.metadata
from app.db import Base

revision: str = "0001_baseline"
down_revision: str | None = None
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

# Topf × Stufe (flaches budget_pot/budget_entry-Modell, T-17).
_MV_USAGE = """
CREATE MATERIALIZED VIEW mv_budget_usage AS
SELECT be.budget_pot_id AS budget_pot_id,
       bp.period        AS period,
       be.stage         AS stage,
       COALESCE(SUM(be.amount), 0) AS total_amount,
       COUNT(*)         AS entry_count
FROM budget_entry be
JOIN budget_pot bp ON bp.id = be.budget_pot_id
GROUP BY be.budget_pot_id, bp.period, be.stage
WITH DATA
"""

_MV_STATUS = """
CREATE MATERIALIZED VIEW mv_status_distribution AS
SELECT a.gremium_id       AS gremium_id,
       a.current_state_id AS current_state_id,
       COUNT(*)           AS application_count
FROM application a
GROUP BY a.gremium_id, a.current_state_id
WITH DATA
"""

# Roll-up der gebundenen Summe: jeder genehmigte Antrag zählt zu seiner Kostenstelle
# (``b.path_key = leaf.path_key``) und allen Vorfahren (``leaf.path_key LIKE b.path_key||'-%'``).
_MV_ROLLUP = """
CREATE MATERIALIZED VIEW mv_budget_rollup AS
SELECT b.id              AS budget_id,
       a.fiscal_year_id  AS fiscal_year_id,
       COALESCE(SUM(a.amount), 0) AS committed
FROM application a
JOIN budget leaf ON leaf.id = a.budget_id
JOIN budget b
  ON b.path_key = leaf.path_key
  OR leaf.path_key LIKE b.path_key || '-%'
JOIN budget_entry be
  ON be.application_id = a.id
 AND be.stage IN ('reserved', 'approved', 'paid')
WHERE a.amount IS NOT NULL
  AND a.fiscal_year_id IS NOT NULL
GROUP BY b.id, a.fiscal_year_id
WITH DATA
"""


def upgrade() -> None:
    bind = op.get_bind()
    # 1. Extensions (vor create_all — Defaults/Typen hängen daran).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    # btree_gist liefert die uuid-/Gleichheits-Operatorklasse für die GIST-EXCLUDE
    # auf ``gremium_membership`` (``ex_gremium_membership_no_overlap``, #AUD-029).
    # ``create_all`` emittiert diese Constraint inline aus dem Modell — auf einer
    # frischen DB MUSS die Extension also schon vor create_all stehen, sonst bricht
    # das CREATE TABLE mit „data type uuid has no default operator class for gist".
    # (Bestands-DBs liefen 0001 ohne diese Constraint; dort legt 0038 sie nach.)
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # 2. Volles Schema aus den Modellen (Single-Source).
    Base.metadata.create_all(bind=bind)

    # 3. Audit-Append-only (Trigger + Grant).
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

    # 4. Materialized Views + Unique-Indizes (CONCURRENTLY-Voraussetzung).
    op.execute(_MV_USAGE)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_budget_usage "
        "ON mv_budget_usage (budget_pot_id, stage)"
    )
    op.execute(_MV_STATUS)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_status_distribution "
        "ON mv_status_distribution (gremium_id, current_state_id) NULLS NOT DISTINCT"
    )
    op.execute(_MV_ROLLUP)
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_budget_rollup "
        "ON mv_budget_rollup (budget_id, fiscal_year_id)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    # MVs zuerst (hängen an den Tabellen), dann das Schema, dann Funktion/Extensions.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_budget_rollup")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_status_distribution")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_budget_usage")
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP FUNCTION IF EXISTS audit_entry_append_only()")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
