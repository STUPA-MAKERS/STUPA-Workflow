"""Link tools: links between any two elements (`/links`, spec 001409).

A link connects two elements of the kinds `application`, `meeting`, `agenda_item`,
`vote`, `appointment`, `gremium`, `invoice`, `expense`, `budget`, `ticket`, `todo`
(a card) and `paperless` (a Paperless document). A link has no direction: it shows in
the links of both ends. Two elements link at most once, never an element to itself, and
two Paperless documents never link.

The caller adds or removes a link when the caller reads both ends and may change at
least one of them (403 `link_forbidden`). The change right of each kind: the edit right
of the Antrag, `session.manage` in the Gremium of a meeting or a TOP, `vote.manage` or
`session.manage` for a vote, the creator or `calendar.manage` for a Termin,
`admin.gremien` for a Gremium, `budget.book` for an invoice or a Buchung,
`budget.structure` for a Kostenstelle, `ticket.manage` for a ticket and the write right
on the board of a card. Only a card gives its readers read access to its links.

A Paperless end needs `paperless.use`, which only the opt-in scope `paperless:use`
lets through (spec 002920): set `ANTRAGSPLATTFORM_SCOPE` to a list with it. A tool takes
a Paperless end as the number of the document in Paperless, and each row and hit with a
Paperless end gives that number as `documentNumber` (spec 002922). The server names the
end by the id of its row, which comes from the number (`document_ref`).
"""

from __future__ import annotations

import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ._common import ToolGroup, api, params

group = ToolGroup()

#: The kind of a Paperless document.
PAPERLESS = "paperless"
#: The high half of the row id of a Paperless document: the bytes of `paperles`. The same
#: rule as `app.modules.paperless.links.document_ref` of the platform.
_PREFIX = int.from_bytes(b"paperles") << 64
_NUMBER_BITS = (1 << 64) - 1


def document_ref(number: int) -> str:
    """The row id of the Paperless document with this number."""
    if number <= 0 or number > _NUMBER_BITS:
        raise ValueError(f"not a Paperless document number: {number}")
    return str(uuid.UUID(int=_PREFIX | number))


def document_number(ref: str) -> int | None:
    """The number of a Paperless document from its row id, or None for another id."""
    try:
        value = uuid.UUID(ref).int
    except ValueError:
        return None
    number = value & _NUMBER_BITS
    return number if value == _PREFIX | number and number > 0 else None


def _wire_id(kind: str, element_id: str) -> str:
    """The id that the server takes: a document number becomes the row id."""
    if kind != PAPERLESS:
        return element_id
    try:
        return document_ref(int(element_id))
    except ValueError as exc:
        raise ValueError(f"a Paperless end takes the document number, not {element_id!r}") from exc


def _end(end: S.LinkEndIn) -> dict[str, str]:
    return {"kind": end.kind, "id": _wire_id(end.kind, end.id)}


def _numbered(row: Any) -> Any:
    """Add `documentNumber` to a row or a hit with a Paperless end."""
    if isinstance(row, dict) and row.get("kind") == PAPERLESS:
        number = document_number(str(row.get("targetId", "")))
        if number is not None:
            return {**row, "documentNumber": number}
    return row


def _links_out(out: Any) -> Any:
    if isinstance(out, dict) and isinstance(out.get("links"), list):
        return {**out, "links": [_numbered(r) for r in out["links"]]}
    return out


@group.tool
async def link_list(kind: S.LinkKind, target_id: str) -> dict:
    """List the links of an element that the caller reads (404 otherwise).

    The answer has `canLink` (the caller may change the element) and `links`: a linked
    Event first, then the other links by kind, the newest first in each kind. Each row has
    `id` (for `link_remove` and `link_view`), the other end (`kind`, `targetId`, and
    `documentNumber` for a Paperless end), `accessible`, `title`, `url`, `detail`,
    `granted`, `card` (for a card end) and `removable`.

    Args:
        kind: The kind of the element.
        target_id: The id of the element; for `paperless` the document number.
    """
    out = await api().get("/links", params={"kind": kind, "id": _wire_id(kind, target_id)})
    return _links_out(out)


@group.tool
async def link_add(a: S.LinkEndIn, b: S.LinkEndIn) -> dict:
    """Link two elements and return the links of `a` (as `link_list`).

    A Paperless end goes by its document number (`{"kind": "paperless", "id": "41"}`) and
    needs `paperless.use`. 422 `link_self` (an element with itself),
    `link_paperless_pair` (two Paperless documents) or `link_target_not_found` (an end
    that the caller does not read), 403 `link_forbidden` (the caller changes neither end,
    an end is a cost centre and the caller holds neither `budget.book` nor
    `budget.structure`, or a Paperless end without `paperless.use`), 409 `link_exists` or
    `event_link_taken` (an Event card and an Antrag, Buchung or invoice that another Event
    links), 503 `paperless_unavailable` while Paperless does not answer.
    """
    out = await api().post("/links", json={"a": _end(a), "b": _end(b)})
    return _links_out(out)


@group.tool
async def link_remove(link_id: str) -> dict:
    """Remove a link from both of its elements (same rule as `link_add`)."""
    return await api().delete(f"/links/{link_id}")


@group.tool
async def link_targets(
    q: str = "",
    kind: S.LinkKind | None = None,
    exclude_kind: S.LinkKind | None = None,
    exclude_id: str | None = None,
) -> list:
    """Find elements that the caller reads, by text (at most 5 per kind).

    Below two characters, the kind `todo` lists the newest cards, the kind `paperless`
    the documents that Paperless added last, and any other kind nothing. A Paperless hit
    has `documentNumber`; the kind needs `paperless.use` and gives nothing without it.

    Args:
        q: Search text.
        kind: One kind only (default: all kinds).
        exclude_kind: With `exclude_id`: leave out this element and the elements that it
            links already.
        exclude_id: The id of the element to leave out; for `paperless` the document
            number.
    """
    hits = await api().get(
        "/links/targets",
        params=params(
            q=q,
            kind=kind or "all",
            excludeKind=exclude_kind,
            excludeId=(
                _wire_id(exclude_kind, exclude_id)
                if exclude_kind is not None and exclude_id is not None
                else exclude_id
            ),
        ),
    )
    return [_numbered(h) for h in hits] if isinstance(hits, list) else hits


@group.tool
async def link_view(link_id: str) -> dict:
    """Read the other end of a link of a card as a reader of the card sees it."""
    return await api().get(f"/links/{link_id}/view")


@group.tool
async def paperless_document_address(kind: S.PaperlessElementKind, element_id: str) -> dict:
    """Read the address of the filed Paperless document of an element.

    `GET /paperless/documents/{kind}/{id}`. Needs `paperless.use` (scope
    `paperless:use`). The answer has no address while the element has no filed document
    or the part of the integration is off.

    Args:
        kind: `protocol`, `application` or `plan`.
        element_id: The id of the protocol, the Antrag or the plan version.
    """
    return await api().get(f"/paperless/documents/{kind}/{element_id}")


def register(mcp: FastMCP) -> None:
    """Register the link tool group."""
    group.register(mcp)
