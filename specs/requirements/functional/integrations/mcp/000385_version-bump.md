---
id: "000385"
title: The MCP version moves with its tools
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-06
replaced_by: S/shared/git/000043
scope:
  - mcp/
---

# The MCP version moves with its tools

A change that adds, removes or renames an MCP tool raises the package version in
`pyproject.toml` and in `__init__.__version__`.

Reason: Packagers see a new tool only through a new version.
