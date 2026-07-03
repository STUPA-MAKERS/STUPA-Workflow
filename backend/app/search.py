"""Server-side fuzzy search: trigram ranking on Postgres, ILIKE fallback.

Builds a WHERE predicate and a rank expression from a search query ``q`` and a
list of searchable columns/expressions. List services must apply both identically
to the count AND the row query so ``total`` never drifts from the hits.

* Postgres: ``pg_trgm`` similarity; rank = max over columns, filter ``rank > threshold``.
  GIN trigram indexes serve these operators.
* Other dialects (SQLite unit stubs): substring ``ILIKE`` over all columns; rank is
  a constant ``0.0`` so callers may always write ``ORDER BY rank DESC``.

``q`` is always a bound parameter, never interpolated into SQL.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, func, literal, or_
from sqlalchemy.ext.asyncio import AsyncSession


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE metacharacters (``\\``, ``%``, ``_``).

    Use as ``col.ilike(f"%{escape_like(v)}%", escape="\\")`` so user-typed
    ``%``/``_`` act as literals, not wildcards (no wildcard injection).
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def dialect_of(session: AsyncSession) -> str:
    """Return the dialect name of the bound engine (``"postgresql"`` / ``"sqlite"`` / …).

    Defensive: without a bound engine, ``"postgresql"`` (prod default).
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
    """Build ``(where_clause, rank_expr)`` for a fuzzy search over ``columns``.

    Postgres uses ``word_similarity(q, text)`` instead of ``similarity``: the
    latter normalizes over the WHOLE column and collapses when a short query runs
    against long text; ``word_similarity`` scores the best sub-word match, the
    right measure for "does the query occur in the field". Rank = max over
    columns, ``where = rank > threshold``; GIN trigram indexes serve both.

    Other dialects (SQLite stubs): ``where = OR(coalesce(col,'') ILIKE %q%)``,
    ``rank = 0.0`` (constant, allows unconditional ``ORDER BY rank``).
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
