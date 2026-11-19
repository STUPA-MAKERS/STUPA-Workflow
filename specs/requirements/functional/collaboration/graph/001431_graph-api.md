---
id: "001431"
title: The graph has its own API
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules
  - mcp
---
# The graph has its own API

The route `GET /api/graph` must answer one page of the graph for the person:
`{nodes, edges, nextCursor}`. A node must have `kind`, `id`, `title`, `date`, `url`,
`granted` and `accessible`. An edge must have `a`, `b` and `source` (`link` or `builtin`). The answer must hold
each edge between a node of the page and a node of this page or of an earlier page. The query
must take `kinds`, `from`, `to`, `gremiumId`, `relations`, `q`, `single`, `noAccess` and `cursor`. The MCP
tool `graph_read` must call the route (F/integrations/mcp/001200).

Reason: One route for the page and for an agent. The cursor lets the client build the graph
up without a second answer that repeats the first.

Test: `test_route_parity.py`, the MCP parity test and a backend unit test that reads two
pages and finds each edge once.
