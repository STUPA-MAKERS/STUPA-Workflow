---
id: "000387"
title: Memberships and roles are read-only in the MCP
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - mcp/antragsplattform_mcp/tools
scope:
  - mcp/
---

# Memberships and roles are read-only in the MCP

No MCP tool must write a membership or a role assignment. They come from the IdP.
