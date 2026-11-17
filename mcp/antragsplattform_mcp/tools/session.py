"""Auth/identity tools: login, whoami, logout, config schemas."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .. import auth
from ._common import ToolGroup, api, cfg, params

group = ToolGroup()


@group.tool
async def login() -> dict:
    """Force an interactive browser login and return the current identity.

    The login opens the platform OAuth page. Use this tool when calls fail with auth
    errors, or to switch users.
    """
    await api()._token(force_login=True)  # intentional re-auth
    return await api().get("/auth/me")


@group.tool
async def whoami() -> dict:
    """Return the logged-in identity: sub, email, roles, permissions, groups, gremien.

    The first use opens a browser login.
    """
    return await api().get("/auth/me")


@group.tool
def logout() -> dict:
    """Forget the cached token.

    The next call requires a fresh browser login.
    """
    return {"loggedOut": auth.logout(cfg())}


@group.tool
async def get_config_schemas() -> dict:
    """Return the authoritative JSON schemas for flow graphs and form fields.

    The flow schemas cover states, transitions, guards and actions. Read these schemas
    before you build a complex flow body or form body.
    """
    return await api().get("/admin/config-schemas")


@group.tool
async def get_profile() -> dict:
    """Return the profile page of the caller: the stored facts and the SSO claims.

    A token request has no SSO token, so the claims are the stored fields.
    """
    return await api().get("/auth/me/profile")


@group.tool
async def search(q: str, lang: str | None = None) -> dict:
    """Search the platform like the command palette: Anträge, Sitzungen, Rechnungen,
    Buchungen, Kostenstellen, Gremien, Personen, Tickets and To-dos.

    Each source shows only what its own list shows to the caller. A query shorter than
    two characters returns nothing.
    """
    return await api().get("/search", params=params(q=q, lang=lang))


@group.tool
async def list_my_agent_grants() -> list:
    """List the own agent tokens (OAuth grants) that are not revoked."""
    return await api().get("/oauth/grants")


@group.tool
async def revoke_my_agent_grant(grant_id: str) -> dict:
    """Revoke one own agent token. Revoking the grant of this session logs it out.

    Ask the user before you call this.
    """
    await api().delete(f"/oauth/grants/{grant_id}")
    return {"revoked": True}


@group.tool
async def revoke_all_my_agent_grants() -> dict:
    """Revoke every own agent token, also the one of this session (the kill switch).

    Ask the user before you call this: every agent of the user stops at once.
    """
    await api().delete("/oauth/grants")
    return {"revoked": True}


def register(mcp: FastMCP) -> None:
    """Register the session tool group."""
    group.register(mcp)
