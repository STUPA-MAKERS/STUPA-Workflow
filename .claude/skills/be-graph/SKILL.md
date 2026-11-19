---
name: be-graph
description: The graph page backend — GET /api/graph answers the elements a person reads as nodes and the relations between them as edges, page by page, behind the permission graph.view. Covers GraphService, the pure build functions (Relation, Node, Filters, shown, page_of), the built-in relation reads (builtin_reads), the node dates (facts), the reuse of LinkResolver for every read rule, and the frontend page pages/graph with its force layout. Use when working on the graph, a new built-in relation, a graph filter, the node order or paging, or graph.view in backend/app/modules/graph.
---

# Graph — `backend/app/modules/graph`

**Does:** Answers the page "Graph" (`/graph`, specs 001420-001432): every element of the eleven link kinds (spec 001400) that the caller reads, with the links of the table `link` and the built-in relations of the data as edges. The module stores nothing. It has NO read rule of its own: `LinkResolver.resolve` (be-todos) decides per element, with the same gates as the "Verknüpft" lists.

**Key files:**
- `router.py` — `GET /graph` behind `require_principal(GRAPH_VIEW)` (`graph.view`). Query: `kinds` (repeatable), `from`, `to`, `gremiumId`, `relations` (`all|links|builtin`), `q`, `single`, `noAccess`, `cursor`.
- `service.py` — `GraphService.page(principal, filters, cursor)`: reads the relations, resolves every ref once, builds the nodes (`node_of`) and hands them to the pure functions. `offset_of` turns the cursor into a node offset (422 `graph_cursor_invalid`).
- `build.py` — pure: `Relation`, `Node`, `Filters`, `merged` (a link and a built-in relation of one pair give one `link` line), `passes`, `shown` (filters, the search with its neighbours, the rule "only with a relation"), `page_of` (60 nodes per page, each edge between a node of the page and a node of this or an earlier page). `UNDATED` = Gremium and cost centre: they pass every period and take the date of their newest neighbour for the order.
- `relations.py` — `link_relations` (table `link`), `builtin_reads()` (one select per built-in relation of spec 001424), `facts` (date and Gremium of each element, spec 001425).
- `schemas.py` — `GraphNode` (`kind`, `id`, `title`, `date`, `url`, `granted`, `accessible`, `detail`), `GraphEdge` (`a`, `b`, `source`), `GraphPage` (`nodes`, `edges`, `nextCursor`).
- Migration `b7e3d9a41c62` seeds `graph.view` for the admin role only (spec 001421). The scope `read` of an OAuth token covers it (`auth/oauth.py`).

**Conventions & gotchas:**
- **Stateless paging.** Each page computes the whole graph again and cuts it by the offset. The order is stable (date, kind, id), so a page never repeats a node. A change of the data between two pages can shift a node; the client then shows it once, by its key.
- **An unreadable element** shows only with `noAccess`, as a node with its kind and id (spec 001422). Without the switch its edges go too. A cost centre shows with a budget read right or as `granted` through a readable card.
- **A kind of a feature that is off** has no node and no edge (`link_kinds_on`, spec 001432).
- **A new built-in relation** is one entry in `builtin_reads()` and one row in spec 001424. A vote with a TOP has no line to the meeting.
- **Layer:** `graph` sits beside `search` in `pyproject.toml` (import-linter), above `todos`.
- The resolver checks an Antrag one by one for a caller without `application.read`, so a large graph is slow for such a caller. The permission is admin only for now.

**Frontend:** `frontend/src/app/pages/graph/` — `graph.component` (filters in the URL query, build-up of 60 nodes per step until 300, then "Mehr laden", panel of the chosen node, list view `?view=list`), `graph-canvas.component` (nodes as buttons over SVG lines, pan, zoom, pinch, roving tab stop with arrow keys), `graph-layout.ts` (pure force layout: `place`, `step`, `settle`, `fit`, `zoomAt`, `nearestIn`), `graph.util.ts` (`merged`, `neighbours`, `filtersOf`/`queryOf`), `_graph-kinds.scss` (the colour of each kind). With reduced motion the layout runs to its end before the paint (`settle`). API: `core/api/graph.service.ts`.

**MCP:** `graph_read` (`tools/session.py`).

**Related:** be-todos (links, `LinkResolver`), be-search, frontend, mcp
