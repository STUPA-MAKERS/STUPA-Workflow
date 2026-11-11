"""Extra branch and line coverage for `AuditService`.

These tests cover the branches that the base unit test misses. They drive
`query_cursor` with and without filters and at the `has_more` limit. They drive
`resolve_actor_names` with an empty and a full input and with the None fallback. They
also drive `list_actors`.

The tests need no database. The result-queue fakes in `tests._support.audit_fakes`
serve `execute` and `stream_scalars`. Each `execute(...).all()` call returns the given
items in order. The resolvers receive tuples.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.audit.service import AuditService
from tests._support.audit_fakes import fake_session, result
from tests._support.identity_rows import sub_ref

_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _uuid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n, version=4)


async def test_query_cursor_no_filters_under_limit() -> None:
    """Without a filter and with fewer rows than `limit`, `has_more` stays False."""
    rows = ["e3", "e2", "e1"]
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(limit=5)
    assert items == rows
    assert has_more is False


async def test_query_cursor_all_filters_and_has_more() -> None:
    """All filter branches read `limit+1` rows, so `has_more` is True and the list trims.

    With limit=2, the query reads three rows.
    """
    rows = ["e3", "e2", "e1"]
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(
        action="login",
        actor="a",
        since=_AT,
        until=_AT,
        before=99,
        limit=2,
    )
    assert items == ["e3", "e2"]
    assert has_more is True


async def test_query_cursor_exactly_limit_has_no_more() -> None:
    """Exactly `limit` rows means there is no further page."""
    rows = ["e2", "e1"]
    db = fake_session(result(*rows))
    items, has_more = await AuditService(db).query_cursor(limit=2)
    assert items == rows
    assert has_more is False


async def test_resolve_actor_names_empty_input_short_circuits() -> None:
    """Only None or empty subs give an empty map without a database access.

    The fake session has no results, because no query may run.
    """
    db = fake_session()
    out = await AuditService(db).resolve_actor_names([None, None])
    assert out == {}


async def test_resolve_actor_names_prefers_display_name_else_email() -> None:
    """The display_name wins, otherwise the email fallback applies (both `or` branches)."""
    rows = [
        sub_ref("sub-1", "Alice", "alice@example.org"),
        sub_ref("sub-2", None, "bob@example.org"),
    ]
    db = fake_session(result(*rows))
    out = await AuditService(db).resolve_actor_names(["sub-1", "sub-2", None])
    assert out == {"sub-1": "Alice", "sub-2": "bob@example.org"}


async def test_list_actors_resolves_names() -> None:
    """The result holds distinct subs with resolved names. A None sub is filtered out.

    The first execute serves scalars().all() for the subs. The second execute runs inside
    resolve_actor_names and returns the name rows.
    """
    subs = ["sub-1", "sub-2", None]
    name_rows = [
        sub_ref("sub-1", "Alice", "alice@example.org"),
        sub_ref("sub-2", None, "bob@example.org"),
    ]
    db = fake_session(result(*subs), result(*name_rows))
    out = await AuditService(db).list_actors()
    assert out == [("sub-1", "Alice"), ("sub-2", "bob@example.org")]


async def test_list_actors_empty_log() -> None:
    """Without an actor the resolve step short-circuits and needs no second query."""
    db = fake_session(result())
    out = await AuditService(db).list_actors()
    assert out == []
