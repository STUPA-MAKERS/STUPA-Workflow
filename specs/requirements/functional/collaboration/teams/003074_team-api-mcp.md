---
id: "003074"
title: Teams have an API and MCP tools
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/modules/gremien
  - mcp
---

# Teams have an API and MCP tools

The API must list, read, create, rename, move and delete teams and change their members under
`/api/teams`. The MCP server must have a tool for each of these routes. Every route must check
the rights of 003063 to 003066 on the server.

Reason: Agents act through the API like a person (MCP rule).

Test: A backend test calls each route without the right and gets 403 or 404.
