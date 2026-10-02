"""Unit tests for the pool helpers in `delegations.pool` (Z5).

The fake session answers each statement from a queue. These tests cover the
Python side: one statement per helper, the result sets, and the choice of the
group name. The integration suite runs the same helpers against Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.modules.delegations import pool
from tests._support.flow_fakes import fake_session, result

GREMIUM_ID = uuid4()
NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)


def _sql(stmt: object) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


async def test_substitutes_for_is_one_union() -> None:
    a, b = uuid4(), uuid4()
    db = fake_session(result(a, b))
    assert await pool.substitutes_for(db, GREMIUM_ID, uuid4(), NOW) == {a, b}
    sql = _sql(db.statements[0])
    assert "UNION" in sql
    assert "delegation_substitute" in sql
    assert "substitute_group_member" in sql
    # The faculty group counts only with an active gremium membership.
    assert "gremium_membership" in sql


async def test_substitutes_for_defaults_the_time() -> None:
    db = fake_session(result())
    assert await pool.substitutes_for(db, GREMIUM_ID, uuid4()) == set()


async def test_group_substitutes_for_reads_the_groups_only() -> None:
    a = uuid4()
    db = fake_session(result(a))
    assert await pool.group_substitutes_for(db, GREMIUM_ID, uuid4()) == {a}
    sql = _sql(db.statements[0])
    assert "delegation_substitute " not in sql
    assert "substitute_group_member" in sql


async def test_substitute_gremien_by_id_and_by_sub() -> None:
    g = uuid4()
    db = fake_session(result(g), result(g))
    assert await pool.substitute_gremien(db, uuid4()) == {g}
    assert await pool.substitute_gremien_for_sub(db, "sub-1") == {g}
    assert "principal" in _sql(db.statements[1])
    assert len(db.statements) == 2


async def test_group_names_for_no_ids_runs_no_query() -> None:
    db = fake_session()
    assert await pool.group_names_for(db, GREMIUM_ID, []) == {}
    assert db.statements == []


async def test_group_names_for_prefers_member_then_the_delegator_group() -> None:
    member, sub, other = uuid4(), uuid4(), uuid4()
    g_mine, g_low, g_member = uuid4(), uuid4(), uuid4()
    db = fake_session(
        result(
            # A member row wins over a substitute row of a lower position.
            (member, "substitute", g_low, {"de": "Low"}, 0),
            (member, "member", g_member, {"de": "Member"}, 5),
            # A later row with a worse rank does not replace the best one.
            (member, "substitute", g_mine, {"de": "Mine"}, 9),
            # For a substitute, the group of the delegator wins over the position.
            (sub, "substitute", g_low, {"de": "Low"}, 0),
            (sub, "substitute", g_mine, {"de": "Mine"}, 9),
            # A group without a name gives an empty map.
            (other, "substitute", g_low, None, 0),
        )
    )
    db.scalar_results = [g_mine]
    names = await pool.group_names_for(
        db, GREMIUM_ID, [member, sub, other, uuid4()], member_id=uuid4()
    )
    assert names == {member: {"de": "Member"}, sub: {"de": "Mine"}, other: {}}


async def test_group_names_for_without_member_takes_the_lowest_position() -> None:
    sub = uuid4()
    g1, g2 = uuid4(), uuid4()
    db = fake_session(
        result(
            (sub, "substitute", g1, {"de": "B"}, 3),
            (sub, "substitute", g2, {"de": "A"}, 1),
        )
    )
    assert await pool.group_names_for(db, GREMIUM_ID, {sub}) == {sub: {"de": "A"}}
    assert db.scalar_results == []
