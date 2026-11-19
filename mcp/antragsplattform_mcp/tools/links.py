"""Link tools: links between any two elements (`/links`, spec 001409).

A link connects two elements of the kinds `application`, `meeting`, `agenda_item`,
`vote`, `appointment`, `gremium`, `invoice`, `expense`, `budget`, `ticket` and `todo`
(a card). A link has no direction: it shows in the links of both ends. Two elements
link at most once, never an element to itself.

The caller adds or removes a link when the caller reads both ends and may change at
least one of them (403 `link_forbidden`). The change right of each kind: the edit right
of the Antrag, `session.manage` in the Gremium of a meeting or a TOP, `vote.manage` or
`session.manage` for a vote, the creator or `calendar.manage` for a Termin,
`admin.gremien` for a Gremium, `budget.book` for an invoice or a Buchung,
`budget.structure` for a Kostenstelle, `ticket.manage` for a ticket and the write right
on the board of a card. Only a card gives its readers read access to its links.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def link_list(kind: S.TodoLinkKind, target_id: str) -> dict:
    """List the links of an element that the caller reads (404 otherwise).

    The answer has `canLink` (the caller may change the element) and `links`: a linked
    Event first, then the other links by kind, the newest first in each kind. Each row has
    `id` (for `link_remove` and `link_view`), the other end (`kind`, `targetId`),
    `accessible`, `title`, `url`, `detail`, `granted`, `card` (for a card end) and
    `removable`.
    """
    return await api().get("/links", params={"kind": kind, "id": target_id})


@group.tool
async def link_add(a: S.LinkEndIn, b: S.LinkEndIn) -> dict:
    """Link two elements and return the links of `a` (as `link_list`).

    422 `link_self` (an element with itself) or `link_target_not_found` (an end that the
    caller does not read), 403 `link_forbidden` (the caller changes neither end), 409
    `link_exists` or `event_link_taken` (an Event card and an Antrag, Buchung or invoice
    that another Event links).
    """
    return await api().post(
        "/links", json={"a": a.model_dump(exclude_none=True), "b": b.model_dump(exclude_none=True)}
    )


@group.tool
async def link_remove(link_id: str) -> dict:
    """Remove a link from both of its elements (same rule as `link_add`)."""
    return await api().delete(f"/links/{link_id}")


@group.tool
async def link_targets(
    q: str = "",
    kind: S.TodoLinkKind | None = None,
    exclude_kind: S.TodoLinkKind | None = None,
    exclude_id: str | None = None,
) -> list:
    """Find elements that the caller reads, by text (at most 5 per kind).

    Below two characters, the kind `todo` lists the newest cards and any other kind
    nothing.

    Args:
        q: Search text.
        kind: One kind only (default: all kinds).
        exclude_kind: With `exclude_id`: leave out this element and the elements that it
            links already.
        exclude_id: The id of the element to leave out.
    """
    return await api().get(
        "/links/targets",
        params=params(q=q, kind=kind or "all", excludeKind=exclude_kind, excludeId=exclude_id),
    )


@group.tool
async def link_view(link_id: str) -> dict:
    """Read the other end of a link of a card as a reader of the card sees it."""
    return await api().get(f"/links/{link_id}/view")


def register(mcp: FastMCP) -> None:
    """Register the link tool group."""
    group.register(mcp)
