---
id: "001076"
title: Free boards are created and managed through the API and MCP
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
implementation: null
scope:
  - backend/app/modules/todos
  - mcp
---

# Free boards are created and managed through the API and MCP

The API must have `POST /api/todos/boards` to create a free board, `DELETE
/api/todos/boards/{id}` to delete it, `POST /api/todos/boards/{id}/archive` and
`/restore`, and `GET`, `POST`, `PATCH` and `DELETE` on `/api/todos/boards/{id}/entries` for the
member entries. The MCP server must have a tool for each of these routes.

Reason: An agent works on the platform as the logged-in person and needs the same functions as
the page.

Test: An MCP test creates a free board and adds a Gremium entry.
