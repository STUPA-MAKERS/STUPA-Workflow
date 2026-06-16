"""TDD: Least-Privilege-DB-Rollen (T-41, security.md §4/§10).

Statischer Check des Provisionierungs-Skripts `deploy/db/roles.sql`: getrennte
Service-User + Audit-Entzug von UPDATE/DELETE für den Runtime-User. Die *Wirkung*
(Trigger blockt UPDATE/DELETE) ist über Migration 0006 + Integration abgedeckt; hier
geht es um die Existenz/Korrektheit des Ops-Skripts (kein DB-Zugriff nötig)."""

from __future__ import annotations

import re
from pathlib import Path

# tests/unit/ → parents[2] = backend, parents[3] = repo root (deploy/ lives there).
_SQL = (
    Path(__file__).resolve().parents[3] / "deploy" / "db" / "roles.sql"
).read_text(encoding="utf-8")


def test_roles_sql_exists_and_nonempty() -> None:
    assert _SQL.strip()


def test_separate_service_users_created() -> None:
    for role in ("migrator", "app", "audit_writer"):
        assert f"rolname = '{role}'" in _SQL, f"role {role} not provisioned"
    # Migrations-User getrennt vom Runtime-User (security.md §10).
    assert "CREATE ROLE migrator LOGIN" in _SQL
    assert "CREATE ROLE app LOGIN" in _SQL


def test_runtime_user_loses_update_delete_on_audit() -> None:
    """App-User ohne U/D (+TRUNCATE) auf `audit_entry` (Akzeptanzkriterium T-41)."""
    revoke = re.search(
        r"REVOKE\s+UPDATE,\s*DELETE,\s*TRUNCATE\s+ON\s+TABLE\s+audit_entry\s+FROM\s+app",
        _SQL,
        re.IGNORECASE,
    )
    assert revoke is not None, "missing audit UPDATE/DELETE revoke for runtime user"
    assert re.search(
        r"GRANT\s+INSERT,\s*SELECT\s+ON\s+TABLE\s+audit_entry\s+TO\s+app",
        _SQL,
        re.IGNORECASE,
    )
