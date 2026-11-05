---
id: "000043"
title: The MCP version rises with the tool set
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - mcp/
---

# The MCP version rises with the tool set

A change that adds, removes or renames an MCP tool must raise `version` in
`mcp/pyproject.toml` and `__version__` in the same change.

Reason: A packager sees a new tool set only through a new version.
