"""The graph of one reader (specs 001420-001426, 001432).

The service reads every relation and resolves every element of a relation for the
reader with the link resolver, so a node shows only by the read rule of its kind or
through a card that the reader reads (spec 001422). The rules of what shows are the pure
functions of ``build``.

Each page reads the whole graph again and cuts one page out of it. The cursor is the
count of the nodes before the page. A change of the data between two pages can move a
node to another page; the client keeps a node that it already shows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.budget.access import has_budget_read
from app.modules.graph import relations as reads
from app.modules.graph.build import Filters, Node, Ref, Relation, page_of, shown
from app.modules.graph.schemas import GraphEdge, GraphNode, GraphPage, GraphRef
from app.modules.todos.access import BoardAccess
from app.modules.todos.grouping import grouped
from app.modules.todos.links import LinkResolver, Resolved, link_kinds_on
from app.shared.errors import ValidationProblem


def offset_of(cursor: str | None) -> int:
    """Read the cursor: the count of the nodes before the page.

    Raises:
        ValidationProblem: The cursor is not a count.
    """
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdigit():
        msg = "The cursor is not valid."
        raise ValidationProblem(
            msg, code="graph_cursor_invalid", errors=[{"field": "cursor", "msg": msg}]
        )
    return int(cursor)


def card_opened(relations: Iterable[Relation], resolved: Mapping[Ref, Resolved]) -> frozenset[Ref]:
    """The cost centres that a link of a card that the reader reads names (spec 000552)."""
    return frozenset(
        other
        for r in relations
        if r.source == "link"
        for own, other in ((r.a, r.b), (r.b, r.a))
        if own[0] == "todo" and other[0] == "budget" and resolved[own].accessible
    )


def node_of(
    ref: Ref,
    found: Resolved,
    fact: reads.Fact | None,
    *,
    budget_reader: bool,
    opened: frozenset[Ref],
) -> Node:
    """One candidate node from the resolved element and its facts.

    The resolver names a cost centre to every person, because a card shows the cost
    centre of its link. In the graph a person without the budget read right gets a cost
    centre only through a card that the person reads, and then as a granted node.
    """
    by_card = ref[0] == "budget" and not budget_reader
    if not found.accessible or (by_card and ref not in opened) or fact is None:
        return Node(ref=ref, accessible=False)
    when, gremien = fact
    return Node(
        ref=ref,
        accessible=True,
        title=found.title,
        url=found.url,
        detail=found.detail,
        granted=found.granted or by_card,
        date=when,
        gremien=gremien,
    )


def _ref_out(ref: Ref) -> GraphRef:
    return GraphRef(kind=ref[0], id=ref[1])  # type: ignore[arg-type]


def _node_out(node: Node) -> GraphNode:
    return GraphNode(
        kind=node.ref[0],  # type: ignore[arg-type]
        id=node.ref[1],
        accessible=node.accessible,
        title=node.title,
        date=node.date,
        url=node.url,
        granted=node.granted,
        detail=node.detail,
    )


class GraphService:
    """The graph as one principal sees it."""

    def __init__(self, session: AsyncSession, links: LinkResolver | None = None) -> None:
        """Bind the service to the link resolver of a session."""
        self.links = links or LinkResolver(session, BoardAccess(session))

    async def page(
        self, principal: Principal, filters: Filters, cursor: str | None = None
    ) -> GraphPage:
        """Read one page of the graph, the newest nodes first.

        A kind of a feature that is off is no kind of the graph (spec 001432).

        Raises:
            ValidationProblem: The cursor is not a count.
        """
        offset = offset_of(cursor)
        session = self.links.session
        on = frozenset(await link_kinds_on(session))
        kinds = on if filters.kinds is None else on & filters.kinds
        relations = (
            *await reads.link_relations(session, kinds),
            *await reads.builtin_relations(session, kinds),
        )
        ends = frozenset(ref for r in relations for ref in (r.a, r.b))
        refs = ends | (await reads.all_refs(session, kinds) if filters.single else frozenset())
        resolved = await self.links.resolve(refs, principal)
        readable = grouped(ref for ref, found in resolved.items() if found.accessible)
        facts = await reads.facts(session, readable)
        opened = card_opened(relations, resolved)
        budget_reader = has_budget_read(principal)
        candidates = {
            ref: node_of(ref, found, facts.get(ref), budget_reader=budget_reader, opened=opened)
            for ref, found in resolved.items()
        }
        nodes, lines = shown(candidates, relations, replace(filters, kinds=kinds))
        page_nodes, page_lines, following = page_of(nodes, lines, offset)
        return GraphPage(
            nodes=tuple(_node_out(n) for n in page_nodes),
            edges=tuple(
                GraphEdge(a=_ref_out(r.a), b=_ref_out(r.b), source=r.source) for r in page_lines
            ),
            nextCursor=str(following) if following is not None else None,
        )
