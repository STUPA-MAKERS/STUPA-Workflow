---
id: "000043"
title: The MCP version rises with the tool set
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - mcp/
scope:
  - mcp/
---

# The MCP version rises with the tool set

A change that adds, removes or renames an MCP tool must raise `version` in
`mcp/pyproject.toml`. The same change must raise `__version__` of the package.

Reason: A packager sees a new tool set only through a new version.
