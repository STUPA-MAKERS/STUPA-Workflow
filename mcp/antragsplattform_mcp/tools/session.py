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
async def list_activity(
    kinds: list[str] | None = None,
    own: bool = False,
    cursor: str | None = None,
    lang: str | None = None,
) -> dict:
    """List the activity page: the events of the Anträge, To-dos, Tickets and Sitzungen
    that the caller made, holds or touched, newest first, 50 per step.

    Args:
        kinds: Limit the hits to ``application``, ``todo``, ``ticket`` and/or ``meeting``.
        own: Show the own actions too; without it they are hidden.
        cursor: The ``nextCursor`` of the step before.
        lang: The language of the state labels (``de`` or ``en``).

    Each source shows only what the detail page of the item shows to the caller.
    """
    return await api().get(
        "/activity", params=params(kind=kinds, own=own or None, cursor=cursor, lang=lang)
    )


@group.tool
async def get_activity_status() -> dict:
    """Tell whether an event of another person waits after the last visit (``hasNew``)."""
    return await api().get("/activity/status")


@group.tool
async def get_navigation_status() -> dict:
    """Read the marks of the navigation in one call.

    ``tasks`` counts the applications to act on plus the open to-dos of the caller,
    ``tickets`` the new tickets (``null`` without ``ticket.manage``), ``live`` tells whether
    a readable meeting runs, ``activity`` whether an event of another person waits.
    """
    return await api().get("/navigation/status")


@group.tool
async def mark_activity_seen(at: str) -> dict:
    """Mark the activity page as seen up to ``at`` (the ``readAt`` of a step).

    The mark never moves back and never past now.
    """
    await api().post("/activity/seen", json={"at": at})
    return {"seen": at}


@group.tool
async def graph_read(
    kinds: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    relations: str | None = None,
    q: str | None = None,
    depth: int | None = None,
    single: bool = False,
    no_access: bool = False,
    cursor: str | None = None,
) -> dict:
    """Read one page of the graph: the elements that the caller reads as ``nodes`` and
    the relations between them as ``edges``, the newest nodes first, 60 per page.

    An edge has the ``source`` ``link`` (a link that a person made) or ``builtin`` (a
    relation of the data, for example a meeting and its TOP). The answer holds each
    edge between a node of the page and a node of this page or of an earlier page.
    Needs the permission ``graph.view``.

    Args:
        kinds: Limit the hits to ``application``, ``meeting``, ``agenda_item``, ``vote``,
            ``appointment``, ``gremium``, ``invoice``, ``expense``, ``budget``,
            ``ticket`` and/or ``todo``.
        date_from: Only hits with their date on or after this day (``YYYY-MM-DD``).
        date_to: Only hits with their date on or before this day.
        relations: ``all`` (default), ``links`` or ``builtin``.
        q: Only hits with the term in their title. A hit of the search shows also
            without a relation.
        depth: Add the neighbours of the hits, up to this count of lines away (0 to 5,
            default 2). A neighbour shows also when it does not pass the filters.
        single: Add the elements without a relation.
        no_access: Add the elements that the caller does not read, as nodes with their
            kind only.
        cursor: The ``nextCursor`` of the page before.
    """
    query = {
        "kinds": kinds,
        "from": date_from,
        "to": date_to,
        "relations": relations,
        "q": q,
        "depth": depth,
        "single": single or None,
        "noAccess": no_access or None,
        "cursor": cursor,
    }
    return await api().get("/graph", params=params(**query))


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
