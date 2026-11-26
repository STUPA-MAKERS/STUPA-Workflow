"""Tool-group modules for the antragsplattform MCP server.

Each module holds one domain group of `@group.tool` functions and a `register(mcp)`
entry. The module order is fixed. It keeps the served tool list stable for agents.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import (
    admin,
    applications,
    budget,
    budget_plan,
    committees,
    events,
    finance,
    flow_forms,
    links,
    meetings,
    orders,
    session,
    settings,
    tickets,
    todos,
)

_GROUPS = (
    session,
    applications,
    flow_forms,
    meetings,
    committees,
    todos,
    links,
    tickets,
    orders,
    events,
    budget,
    budget_plan,
    finance,
    admin,
    settings,
)


def register_all(mcp: FastMCP) -> None:
    """Register every tool group on the shared FastMCP instance."""
    for module in _GROUPS:
        module.register(mcp)
