"""Ticket tools: the reported problems, questions and ideas of the help menu.

Every tool needs the global permission `ticket.manage` and the scope `tickets:write`.
A reporter never reads a ticket, so there is no reporter tool.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def tickets_list(
    status: list[Literal["new", "in_progress", "done", "rejected"]] | None = None,
    kind: list[Literal["bug", "question", "idea"]] | None = None,
    assignee: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List the tickets, newest first, offset-paged.

    Args:
        status: Keep only these statuses.
        kind: Keep only these kinds.
        assignee: A principal id, `me` or `none`.
        q: Matches the title, the body, the number (`T-0040`, `40`) and the reporter.
    """
    return await api().get(
        "/tickets",
        params=params(
            status=status, kind=kind, assignee=assignee, q=q, limit=limit, offset=offset
        ),
    )


@group.tool
async def tickets_get(ticket_id: str) -> dict:
    """Get one ticket with body, technical context, attachments, notes and events."""
    return await api().get(f"/tickets/{ticket_id}")


@group.tool
async def tickets_note(ticket_id: str, body: str) -> dict:
    """Add an internal note to a ticket. The reporter never sees it.

    Args:
        body: Markdown, 1 to 10000 characters.
    """
    return await api().post(f"/tickets/{ticket_id}/notes", json={"body": body})


@group.tool
async def tickets_update(ticket_id: str, patch: S.TicketPatch) -> dict:
    """Change the status, the assignee or the kind of a ticket.

    Each change writes an event. An assignee without ticket.manage gives 422
    `assignee_not_allowed`. `duplicateOfId` goes only with status `rejected`
    (422 `duplicate_invalid` otherwise). With status `done` or `rejected`,
    `completeTodos: true` also completes the open linked to-dos the caller can write.
    """
    return await api().patch(f"/tickets/{ticket_id}", json=dump_patch(patch))


def register(mcp: FastMCP) -> None:
    """Register the ticket tool group."""
    group.register(mcp)
