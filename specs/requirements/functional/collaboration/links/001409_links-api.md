---
id: "001409"
title: The links have their own API
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/links/router.py
  - mcp/antragsplattform_mcp/tools/links.py
scope:
  - backend/app/modules/links
  - backend/app/modules/todos
  - mcp/
---

# The links have their own API

The API must have these routes for links:

| Route | Use |
| --- | --- |
| `GET /api/links?kind=&id=` | the links of an element, resolved for the reader |
| `POST /api/links` | add a link, body `{a: {kind, id}, b: {kind, id}}` |
| `DELETE /api/links/{id}` | remove a link |
| `GET /api/links/targets?q=&kind=&excludeKind=&excludeId=` | the search of 001408 |
| `GET /api/links/{id}/view` | the read-only view of a granted end (000487) |

The routes `POST/DELETE /api/todos/cards/{id}/links`, `GET /api/todos/link-targets` and
`GET /api/todos/linked` must be removed in the same pull request. The MCP tools `link_list`,
`link_add`, `link_remove`, `link_targets` and `link_view` must replace the tools `todo_card_link_*`,
`todo_link_targets` and `todo_linked`. The card detail must keep its links in its response.

Reason: A link no longer belongs to a card. The frontend and the MCP server ship with the
backend, so no other client needs the old routes.

Test: `test_route_parity.py` and a backend unit test per route.
