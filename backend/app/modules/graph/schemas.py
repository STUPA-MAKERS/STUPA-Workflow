"""Schemas of the graph page (spec 001431).

A node is one element as the reader sees it, a line is a relation between two nodes.
The answer is one page of the graph; the client adds each page to the drawing.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.modules.todos.schemas import TodoLinkDetail, TodoLinkKind
from app.shared.schemas import FrozenCamelModel

#: Where a relation comes from: a link that a person made, or a relation of the data model.
RelationSource = Literal["link", "builtin"]
#: The choices of the filter "Beziehungen" (spec 001424).
RelationFilter = Literal["all", "links", "builtin"]


class GraphRef(FrozenCamelModel, frozen=True):
    """One end of a line: the kind and the id of a node."""

    kind: TodoLinkKind
    id: UUID


class GraphNode(FrozenCamelModel, frozen=True):
    """One element of the graph.

    A node with ``accessible`` false is an element that the reader does not read (spec
    001422): it has its kind and its id only.
    """

    kind: TodoLinkKind
    id: UUID
    accessible: bool
    title: str | None = None
    date: date | None = None
    #: The detail page, app-relative. A granted node has none: it opens in the read view.
    url: str | None = None
    #: Readable only through a card (spec 000487).
    granted: bool = False
    #: The facts of the element that the panel shows, as in ``Verknüpft``.
    detail: TodoLinkDetail | None = None


class GraphEdge(FrozenCamelModel, frozen=True):
    """One line between two nodes."""

    a: GraphRef
    b: GraphRef
    source: RelationSource


class GraphPage(FrozenCamelModel, frozen=True):
    """One page of the graph, the newest nodes first.

    ``edges`` holds each line between a node of this page and a node of this page or of
    an earlier page, so the client gets each line once.
    """

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
