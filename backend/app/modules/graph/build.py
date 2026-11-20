"""The rules of the graph as pure functions (specs 001422-001426, 001434).

``shown`` takes every candidate node and every relation and gives the nodes and the lines
that the reader sees with the filters, in the order of the build-up. ``page_of`` cuts one
page out of that order. No function here reads the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import groupby
from typing import Literal

from app.modules.todos.models import LINK_KINDS
from app.modules.todos.schemas import TodoLinkDetail

Ref = tuple[str, uuid.UUID]
Source = Literal["link", "builtin"]
RelationChoice = Literal["all", "links", "builtin"]

#: The kinds without a date: they pass every period (spec 001425).
UNDATED: frozenset[str] = frozenset({"gremium", "budget"})
#: The most lines from a hit to a neighbour that shows, and the choice of a fresh page
#: (spec 001434).
MAX_DEPTH = 5
DEFAULT_DEPTH = 2
#: The most nodes of one page (spec 001426).
PAGE_SIZE = 60


@dataclass(frozen=True, slots=True)
class Relation:
    """A relation between two elements."""

    a: Ref
    b: Ref
    source: Source


@dataclass(frozen=True, slots=True)
class Node:
    """One candidate element with what the filters need."""

    ref: Ref
    accessible: bool
    title: str | None = None
    url: str | None = None
    detail: TodoLinkDetail | None = None
    granted: bool = False
    date: date | None = None


@dataclass(frozen=True, slots=True)
class Filters:
    """The filters of the page (spec 001425) and its switches (specs 001422, 001423)."""

    kinds: frozenset[str] | None = None
    start: date | None = None
    end: date | None = None
    relations: RelationChoice = "all"
    q: str = ""
    single: bool = False
    no_access: bool = False
    #: The lines from a hit to the farthest neighbour that shows (spec 001434).
    depth: int = 0


def _key(ref: Ref) -> tuple[int, str]:
    return (LINK_KINDS.index(ref[0]), str(ref[1]))


def _pair(relation: Relation) -> tuple[Ref, Ref]:
    """The two ends in a fixed order, so both directions of a relation are one pair."""
    first, second = sorted((relation.a, relation.b), key=_key)
    return (first, second)


def merged(relations: Iterable[Relation]) -> tuple[Relation, ...]:
    """One relation per pair of elements; a link wins over a built-in relation."""
    by_pair = {
        _pair(r): r for r in sorted(relations, key=lambda r: r.source == "link") if r.a != r.b
    }
    return tuple(Relation(a=a, b=b, source=r.source) for (a, b), r in by_pair.items())


def _in_period(node: Node, filters: Filters) -> bool:
    if filters.start is None and filters.end is None:
        return True
    if node.date is None:
        return node.ref[0] in UNDATED
    return (filters.start is None or node.date >= filters.start) and (
        filters.end is None or node.date <= filters.end
    )


def passes(node: Node, filters: Filters) -> bool:
    """Tell if the node passes the filters of its own facts.

    A node that the reader does not read passes only with the switch, and then without
    the period, because it would tell its facts (spec 001422).
    """
    if filters.kinds is not None and node.ref[0] not in filters.kinds:
        return False
    if not node.accessible:
        return filters.no_access
    return _in_period(node, filters)


def _wanted(source: Source, choice: RelationChoice) -> bool:
    match choice:
        case "all":
            return True
        case "links":
            return source == "link"
        case "builtin":
            return source == "builtin"


def _ends(relations: Iterable[Relation]) -> frozenset[Ref]:
    return frozenset(ref for r in relations for ref in (r.a, r.b))


def _between(relations: Iterable[Relation], refs: Collection[Ref]) -> tuple[Relation, ...]:
    return tuple(r for r in relations if r.a in refs and r.b in refs)


def _matches(node: Node, term: str) -> bool:
    return node.accessible and term in (node.title or "").casefold()


def _within(
    seen: frozenset[Ref], edge: frozenset[Ref], lines: Sequence[Relation], steps: int
) -> frozenset[Ref]:
    """The nodes at most ``steps`` lines away from ``seen``; ``edge`` is its newest ring."""
    if steps <= 0 or not edge:
        return seen
    ring = (
        frozenset(other for r in lines for own, other in ((r.a, r.b), (r.b, r.a)) if own in edge)
        - seen
    )
    return _within(seen | ring, ring, lines, steps - 1)


def _ordered(nodes: Mapping[Ref, Node], lines: Sequence[Relation]) -> tuple[Node, ...]:
    """The newest first; a node without a date takes the newest date of its neighbours.

    A Gremium or a cost centre then appears together with the first element that it
    connects, next to a neighbour that already shows (spec 001426).
    """
    dated = {ref: n.date for ref, n in nodes.items() if n.date is not None}
    linked = sorted(
        (
            (own, dated[other])
            for r in lines
            for own, other in ((r.a, r.b), (r.b, r.a))
            if own not in dated and other in dated
        ),
        key=lambda pair: _key(pair[0]),
    )
    near = {own: max(d for _, d in group) for own, group in groupby(linked, key=lambda p: p[0])}
    when = {**dict.fromkeys(nodes, date.min), **near, **dated}
    return tuple(sorted(nodes.values(), key=lambda n: (-when[n.ref].toordinal(), *_key(n.ref))))


def shown(
    candidates: Mapping[Ref, Node], relations: Iterable[Relation], filters: Filters
) -> tuple[tuple[Node, ...], tuple[Relation, ...]]:
    """Return the nodes, in the order of the build-up, and the lines of the graph.

    A hit is a node that passes the filters and the search. The neighbours of a hit show
    too, up to ``filters.depth`` lines away, also when they do not pass the kind, the
    period or the search (spec 001434). A line shows when both ends show and
    the reader reads at least one of them. A node shows when it has a line, or with the
    switch "Auch ohne Verknüpfung" when it is a hit that the reader reads (spec 001423).
    """
    allowed = {
        ref: node for ref, node in candidates.items() if node.accessible or filters.no_access
    }
    lines = tuple(
        r
        for r in merged(relations)
        if _wanted(r.source, filters.relations)
        and r.a in allowed
        and r.b in allowed
        and (allowed[r.a].accessible or allowed[r.b].accessible)
    )
    term = filters.q.strip().casefold()
    hits = frozenset(
        ref
        for ref, node in allowed.items()
        if passes(node, filters) and (not term or _matches(node, term))
    )
    reach = _within(hits, hits, lines, filters.depth)
    final = _between(lines, reach)
    connected = _ends(final)
    nodes = {
        ref: allowed[ref]
        for ref in reach
        if ref in connected or (filters.single and ref in hits and allowed[ref].accessible)
    }
    return (_ordered(nodes, final), final)


def page_of(
    nodes: Sequence[Node], lines: Iterable[Relation], offset: int, size: int = PAGE_SIZE
) -> tuple[tuple[Node, ...], tuple[Relation, ...], int | None]:
    """Cut one page: its nodes, the lines that end in it, and the next offset.

    A line belongs to the page of its later end, so the pages give each line once and
    never before both of its nodes.
    """
    index = {node.ref: i for i, node in enumerate(nodes)}
    last = offset + size
    return (
        tuple(nodes[offset:last]),
        tuple(r for r in lines if offset <= max(index[r.a], index[r.b]) < last),
        last if last < len(nodes) else None,
    )
