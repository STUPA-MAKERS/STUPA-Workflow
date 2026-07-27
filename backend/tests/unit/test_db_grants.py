"""Static checks of the least-privilege database roles (T-41, security.md §4/§10).

The tests read the provisioning script `deploy/db/roles.sql`. They check that the script
creates separate service users. They also check that it revokes UPDATE and DELETE on the
audit table from the runtime user. Migration 0006 and the integration tests cover the
effect of the trigger that blocks UPDATE and DELETE. These tests need no database access.
"""

from __future__ import annotations

import re
from pathlib import Path

# From tests/unit/, parents[2] is backend and parents[3] is the repo root that holds deploy/.
_SQL = (
    Path(__file__).resolve().parents[3] / "deploy" / "db" / "roles.sql"
).read_text(encoding="utf-8")


def test_roles_sql_exists_and_nonempty() -> None:
    assert _SQL.strip()


def test_separate_service_users_created() -> None:
    for role in ("migrator", "app", "audit_writer"):
        assert f"rolname = '{role}'" in _SQL, f"role {role} not provisioned"
    # The migration user must stay separate from the runtime user (security.md §10).
    assert "CREATE ROLE migrator LOGIN" in _SQL
    assert "CREATE ROLE app LOGIN" in _SQL


def test_runtime_user_loses_update_delete_on_audit() -> None:
    """The app user has no UPDATE, DELETE or TRUNCATE on `audit_entry`.

    This is the acceptance criterion of T-41.
    """
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
