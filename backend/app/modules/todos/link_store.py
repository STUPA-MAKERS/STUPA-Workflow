"""Read and write the rows of ``link`` from the side of one end (specs 001400-001402).

A link has no direction, so each read asks for the links of an element by its kind and
id and gets the other end of each link. ``Edge`` is a link as one end sees it.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, CompoundSelect, Select, and_, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.todos.grouping import grouped
from app.modules.todos.models import Link, LinkEnd, ordered_ends


@dataclass(frozen=True, slots=True)
class Edge:
    """A link as the end ``(own_kind, own_id)`` sees it: ``(kind, target_id)`` is the other."""

    id: uuid.UUID
    own_kind: str
    own_id: uuid.UUID
    kind: str
    target_id: uuid.UUID
    created_by: uuid.UUID
    created_at: datetime

    @property
    def target(self) -> LinkEnd:
        """The other end."""
        return (self.kind, self.target_id)


def edges_stmt(
    own_kind: str, own_ids: Collection[uuid.UUID], kinds: Collection[str] | None = None
) -> Select[Any, Any, Any, Any, Any, Any, Any]:
    """The links of the elements ``own_ids`` of ``own_kind``, as the rows of ``Edge``.

    ``kinds`` keeps only the links whose other end has one of these kinds.
    """
    ids = list(own_ids)
    only_a = (Link.a_kind.in_(list(kinds)),) if kinds is not None else ()
    only_b = (Link.b_kind.in_(list(kinds)),) if kinds is not None else ()
    from_a = select(
        Link.id.label("id"),
        literal(own_kind).label("own_kind"),
        Link.a_id.label("own_id"),
        Link.b_kind.label("kind"),
        Link.b_id.label("target_id"),
        Link.created_by.label("created_by"),
        Link.created_at.label("created_at"),
    ).where(Link.a_kind == own_kind, Link.a_id.in_(ids), *only_b)
    from_b = select(
        Link.id.label("id"),
        literal(own_kind).label("own_kind"),
        Link.b_id.label("own_id"),
        Link.a_kind.label("kind"),
        Link.a_id.label("target_id"),
        Link.created_by.label("created_by"),
        Link.created_at.label("created_at"),
    ).where(Link.b_kind == own_kind, Link.b_id.in_(ids), *only_a)
    both = union_all(from_a, from_b).subquery()
    return select(
        both.c.id,
        both.c.own_kind,
        both.c.own_id,
        both.c.kind,
        both.c.target_id,
        both.c.created_by,
        both.c.created_at,
    ).order_by(both.c.created_at, both.c.id)


async def edges(
    session: AsyncSession,
    own_kind: str,
    own_ids: Collection[uuid.UUID],
    kinds: Collection[str] | None = None,
) -> list[Edge]:
    """The links of the elements ``own_ids``, the oldest first."""
    if not own_ids:
        return []
    rows = (await session.execute(edges_stmt(own_kind, own_ids, kinds))).all()
    return [Edge(*row) for row in rows]


def linked_ids(
    own_kind: str, kind: str, targets: Collection[uuid.UUID] | Select[uuid.UUID]
) -> CompoundSelect[uuid.UUID]:
    """The ids of the elements of ``own_kind`` that link one of ``targets`` of ``kind``.

    ``targets`` is a set of ids or a select of ids. The column of the result is ``own_id``.
    """
    ids = targets if isinstance(targets, Select) else list(targets)
    return union_all(
        select(Link.a_id.label("own_id")).where(
            Link.a_kind == own_kind, Link.b_kind == kind, Link.b_id.in_(ids)
        ),
        select(Link.b_id.label("own_id")).where(
            Link.b_kind == own_kind, Link.a_kind == kind, Link.a_id.in_(ids)
        ),
    )


def pair_condition(one: LinkEnd, other: LinkEnd) -> ColumnElement[bool]:
    """The condition of the link between two ends."""
    (a_kind, a_id), (b_kind, b_id) = ordered_ends(one, other)
    return and_(Link.a_kind == a_kind, Link.a_id == a_id, Link.b_kind == b_kind, Link.b_id == b_id)


def any_end(end: LinkEnd) -> ColumnElement[bool]:
    """The condition of every link with the end ``end``."""
    kind, target_id = end
    return or_(
        and_(Link.a_kind == kind, Link.a_id == target_id),
        and_(Link.b_kind == kind, Link.b_id == target_id),
    )


async def link_between(session: AsyncSession, one: LinkEnd, other: LinkEnd) -> Link | None:
    """The link between two ends, if any."""
    return await session.scalar(select(Link).where(pair_condition(one, other)))


def edge_of(link: Link, own: LinkEnd) -> Edge:
    """The link as the end ``own`` sees it."""
    kind, target_id = link.other(own)
    return Edge(
        id=link.id,
        own_kind=own[0],
        own_id=own[1],
        kind=kind,
        target_id=target_id,
        created_by=link.created_by,
        created_at=link.created_at,
    )


def ends_by_kind(found: Sequence[Edge]) -> dict[str, set[uuid.UUID]]:
    """The other ends of the edges, grouped by kind."""
    return {kind: set(ids) for kind, ids in grouped(e.target for e in found).items()}
