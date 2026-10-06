"""O21: the search text of a reader without the PII right skips the isPII keys."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql, sqlite

from app.modules.applications.service.listing import ListingOps


def _sql(dialect: str, *, hidden: set[str], owner: str | None) -> str:
    expr = ListingOps._search_text(dialect, hidden_keys=hidden, owner_sub=owner)
    compiler = postgresql.dialect() if dialect == "postgresql" else sqlite.dialect()
    return str(expr.compile(dialect=compiler, compile_kwargs={"literal_binds": True}))


def test_full_text_without_hidden_keys() -> None:
    assert _sql("postgresql", hidden=set(), owner=None) == "app_search_text(application.data)"
    assert "json_remove" not in _sql("sqlite", hidden=set(), owner="me")


def test_postgres_projection_removes_the_keys() -> None:
    sql = _sql("postgresql", hidden={"iban", "name"}, owner=None)
    assert "app_search_text(application.data - CAST(ARRAY['iban', 'name']" in sql
    assert "CASE" not in sql


def test_own_applications_keep_the_full_text() -> None:
    sql = _sql("postgresql", hidden={"iban"}, owner="me")
    assert "CASE WHEN (application.created_by = 'me')" in sql
    assert "app_search_text(application.data)" in sql


def test_sqlite_projection_removes_the_keys() -> None:
    sql = _sql("sqlite", hidden={"iban"}, owner=None)
    assert "json_remove(application.data, '$.\"iban\"')" in sql
