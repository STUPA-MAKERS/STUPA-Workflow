"""Shared runtime for the tool-group modules.

This module holds the lazy process-wide `Config` and `ApiClient` singletons and small
helpers. Tool functions stay at module level and are not nested in `register`. Their
docstrings are the user-facing tool descriptions. Module level keeps the indentation of
those docstrings identical across Python versions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server.fastmcp import FastMCP

from ..client import ApiClient
from ..config import Config

_config: Config | None = None
_client: ApiClient | None = None

F = TypeVar("F", bound=Callable[..., Any])


def cfg() -> Config:
    """Return the process-wide config, built from the environment on first use."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def api() -> ApiClient:
    """Return the process-wide API client, built on first use."""
    global _client
    if _client is None:
        _client = ApiClient(cfg())
    return _client


def params(**kw: Any) -> dict[str, Any]:
    """Drop None values so optional arguments stay off the wire."""
    return {k: v for k, v in kw.items() if v is not None}


class ToolGroup:
    """Collects tool functions and registers them on a FastMCP server in order."""

    def __init__(self) -> None:
        self._fns: list[Callable[..., Any]] = []

    def tool(self, fn: F) -> F:
        """Mark a function as a tool of this group.

        The registration order follows the decoration order.
        """
        self._fns.append(fn)
        return fn

    def register(self, mcp: FastMCP) -> None:
        """Register all collected functions as FastMCP tools."""
        for fn in self._fns:
            mcp.tool()(fn)
