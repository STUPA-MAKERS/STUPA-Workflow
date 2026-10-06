"""Unit tests for the pool helpers in `delegations.pool`.

The fake session answers each statement from a queue. These tests cover the
Python side: one statement per helper and the result sets. The integration
suite runs the same helpers against Postgres.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.modules.delegations import pool
from tests._support.flow_fakes import fake_session, result

GREMIUM_ID = uuid4()


def _sql(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


async def test_substitutes_for_reads_the_pool_table_only() -> None:
    a, b = uuid4(), uuid4()
    db = fake_session(result(a, b))
    assert await pool.substitutes_for(db, GREMIUM_ID, uuid4()) == {a, b}
    sql = _sql(db.statements[0])
    assert "delegation_substitute" in sql
    assert "UNION" not in sql
    assert "substitute_group" not in sql


async def test_substitute_gremien_by_id_and_by_sub() -> None:
    g = uuid4()
    db = fake_session(result(g), result(g))
    assert await pool.substitute_gremien(db, uuid4()) == {g}
    assert await pool.substitute_gremien_for_sub(db, "sub-1") == {g}
    assert "principal" in _sql(db.statements[1])
    assert "substitute_group" not in _sql(db.statements[0])
    assert len(db.statements) == 2
