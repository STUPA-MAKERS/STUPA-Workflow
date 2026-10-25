"""Server-side fuzzy search: trigram ranking on Postgres, ILIKE fallback.

The module builds a WHERE predicate and a rank expression from a search query `q`
and a list of searchable columns or expressions. A list service must apply both to
the count query AND to the row query in the same way. Then `total` never drifts
from the hits.

* Postgres: `pg_trgm` similarity. The rank is the maximum over the columns, and the
  filter is `rank > threshold`. GIN trigram indexes serve these operators.
* Other dialects (SQLite unit stubs): substring `ILIKE` over all columns. The rank
  is the constant `0.0`, so a caller can always write `ORDER BY rank DESC`.

`q` is always a bound parameter. The code never interpolates it into SQL.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, func, literal, or_
from sqlalchemy.ext.asyncio import AsyncSession


def escape_like(value: str) -> str:
    r"""Escape the LIKE and ILIKE metacharacters `\`, `%` and `_`.

    Call it as `col.ilike(f"%{escape_like(v)}%", escape="\\")`. A `%` or a `_` that
    the user typed then acts as a literal and not as a wildcard. This blocks
    wildcard injection.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def dialect_of(session: AsyncSession) -> str:
    """Return the dialect name of the bound engine, such as `postgresql` or `sqlite`.

    Without a bound engine the function returns `postgresql`, the production default.
    """
    bind = session.bind
    return bind.dialect.name if bind is not None else "postgresql"


def trigram_rank(
    q: str,
    columns: list[Any],
    *,
    threshold: float = 0.3,
    dialect: str = "postgresql",
) -> tuple[ColumnElement[bool], ColumnElement[Any]]:
    """Build `(where_clause, rank_expr)` for a fuzzy search over `columns`.

    Postgres uses `word_similarity(q, text)` and not `similarity`. `similarity`
    normalizes over the WHOLE column and collapses when a short query runs against
    long text. `word_similarity` scores the best sub-word match. That is the right
    measure for the question "does the query occur in the field". The rank is the
    maximum over the columns, and `where` is `rank > threshold`. GIN trigram indexes
    serve both.

    Other dialects (SQLite stubs) give `where = OR(coalesce(col,'') ILIKE %q%)` and
    the constant `rank = 0.0`. The constant allows an unconditional `ORDER BY rank`.
    """
    needle = (q or "").strip()
    if dialect == "postgresql":
        sims = [func.word_similarity(needle, func.coalesce(col, "")) for col in columns]
        rank_expr: ColumnElement[Any] = func.greatest(*sims) if len(sims) > 1 else sims[0]
        where_clause = rank_expr > threshold
        return where_clause, rank_expr
    like = f"%{escape_like(needle)}%"
    where_clause = or_(
        *[func.coalesce(col, "").ilike(like, escape="\\") for col in columns]
    )
    return where_clause, literal(0.0)
