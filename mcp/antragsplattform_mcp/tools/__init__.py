"""Tool-group modules for the antragsplattform MCP server.

Each module holds one domain group of `@group.tool` functions and a `register(mcp)`
entry. The module order is fixed. It keeps the served tool list stable for agents.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import admin, applications, budget, finance, flow_forms, meetings, session

_GROUPS = (session, applications, flow_forms, meetings, budget, finance, admin)


def register_all(mcp: FastMCP) -> None:
    """Register every tool group on the shared FastMCP instance."""
    for module in _GROUPS:
        module.register(mcp)
