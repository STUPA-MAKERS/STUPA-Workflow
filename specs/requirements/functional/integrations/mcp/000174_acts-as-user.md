---
id: "000174"
title: The MCP server acts as the logged-in user
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - mcp/
  - backend/app/modules/auth
---

# The MCP server acts as the logged-in user

The MCP server must act on the platform through the API as the logged-in user with a PKCE
grant. It must have no rights of its own.
