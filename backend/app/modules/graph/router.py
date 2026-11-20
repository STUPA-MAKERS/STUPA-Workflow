"""Graph API (spec 001431).

* ``GET /api/graph`` — one page of the graph of the caller.

The route needs the global permission ``graph.view`` (spec 001421). The permission opens
the page only: each node passes the read rule of its kind inside the service (spec
001422).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_principal
from app.modules.auth.principal import Principal
from app.modules.graph.build import Filters
from app.modules.graph.schemas import GraphPage, RelationFilter
from app.modules.graph.service import GraphService
from app.modules.todos.schemas import TodoLinkKind
from app.shared.errors import ProblemDetail

#: The permission of the page "Graph".
GRAPH_VIEW = "graph.view"

router = APIRouter(tags=["graph"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

Viewer = Annotated[Principal, Depends(require_principal(GRAPH_VIEW))]


@router.get(
    "/graph",
    response_model=GraphPage,
    responses={401: _PROBLEM, 403: _PROBLEM, 422: _PROBLEM},
)
async def read_graph(
    session: DbSession,
    principal: Viewer,
    kinds: Annotated[list[TodoLinkKind] | None, Query()] = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    gremium_id: Annotated[UUID | None, Query(alias="gremiumId")] = None,
    relations: RelationFilter = "all",
    q: Annotated[str, Query(max_length=200)] = "",
    single: bool = False,
    no_access: Annotated[bool, Query(alias="noAccess")] = False,
    cursor: Annotated[str | None, Query(max_length=12)] = None,
) -> GraphPage:
    """Read one page of the graph, the newest nodes first, 60 nodes per page.

    ``kinds`` limits the nodes to these kinds, ``from`` and ``to`` to a period,
    ``gremiumId`` to a Gremium and ``q`` to the nodes with the term in the title and their
    neighbours. ``relations`` picks the links, the built-in relations or both. ``single``
    adds the elements without a relation, ``noAccess`` the elements that the caller does
    not read, as nodes with their kind only. ``cursor`` is the ``nextCursor`` of the page
    before.
    """
    return await GraphService(session).page(
        principal,
        Filters(
            kinds=frozenset(kinds) if kinds else None,
            start=start,
            end=end,
            gremium=gremium_id,
            relations=relations,
            q=q,
            single=single,
            no_access=no_access,
        ),
        cursor,
    )
