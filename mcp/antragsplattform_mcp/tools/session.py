"""Auth/identity tools: login, whoami, logout, config schemas."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .. import auth
from ._common import ToolGroup, api, cfg

group = ToolGroup()


@group.tool
async def login() -> dict:
    """Force an interactive browser login (opens the platform OAuth page) and return the
    current identity. Use this if calls fail with auth errors, or to switch users."""
    await api()._token(force_login=True)  # noqa: SLF001 — intentional re-auth
    return await api().get("/auth/me")


@group.tool
async def whoami() -> dict:
    """Return the logged-in identity: sub, email, roles, permissions, groups, gremien.
    Triggers a browser login on first use."""
    return await api().get("/auth/me")


@group.tool
def logout() -> dict:
    """Forget the cached token. The next call requires a fresh browser login."""
    return {"loggedOut": auth.logout(cfg())}


@group.tool
async def get_config_schemas() -> dict:
    """Authoritative JSON-Schemas for flow graphs (states/transitions/guards/actions)
    and form fields — consult before building complex flow/form bodies."""
    return await api().get("/admin/config-schemas")


def register(mcp: FastMCP) -> None:
    """Register the session tool group."""
    group.register(mcp)
