---
id: "000174"
title: The MCP server acts as the logged-in user
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - mcp/
  - backend/app/modules/auth
---

# The MCP server acts as the logged-in user

The MCP server acts on the platform through the API as the logged-in user with a PKCE grant.
It has no rights of its own.
