"""Event tools: the Veranstaltungen (`/events`).

An Event is an element of its own with a team, not a card. A member of the team reads
and writes it; for any other caller it does not exist (404). The status is a key of the
list `event` (`status_list`). The money of an Event comes from its links: the Anträge,
the Buchungen and the invoices that a link joins to it (`link_add` with the kind
`event`). An Antrag, a Buchung or an invoice links at most one Event.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params
from .meetings import download_to

group = ToolGroup()

EventSegment = Literal["upcoming", "past", "done", "void"]


def _filter(
    segment: EventSegment | None, team: str | None, series: str | None, q: str | None
) -> dict[str, object]:
    """The filter of the event list as query parameters, without the empty ones."""
    return params(segment=segment, team=team, series=series, q=q)


@group.tool
async def event_list(
    segment: EventSegment | None = None,
    team: str | None = None,
    series: str | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List the Events of the teams of the caller (paged).

    `segment` is `upcoming` (open, the end today or later, or no date), `past` (open,
    the end before today), `done` or `void` (the phase of the status). `team` and
    `series` are ids. `q` searches the number (`V-` and eight characters), the title and
    the place. An item has `id`, `number`, `title`, `status`, `phase`, `teamId`,
    `teamName`, `seriesId`, `seriesName`, the dates and times, `place`, `participants`,
    `shopUrl`, `descriptionMd`, `totals` (`requested`, `approved`, `expenses`, `income`,
    `balance`) and `version`.
    """
    query = {**_filter(segment, team, series, q), **params(limit=limit, offset=offset)}
    return await api().get("/events", params=query)


@group.tool
async def event_get(event_id: str) -> dict:
    """Return one Event with its totals, its decisions and the other editions of its series."""
    return await api().get(f"/events/{event_id}")


@group.tool
async def event_teams() -> list:
    """List the teams of the caller: the teams that a new Event can have."""
    return await api().get("/events/teams")


@group.tool
async def event_create(event: S.EventCreate) -> dict:
    """Create an Event in a team of the caller with the start status of the list `event`.

    403 `event_team_forbidden` for a team of which the caller is no member, 422
    `event_url_invalid` for a shop link that is not http or https, 422 `series_not_found`,
    422 `status_unknown`, 422 for dates that do not fit (the end before the start, a time
    without its day).
    """
    return await api().post("/events", json=dump_create(event))


@group.tool
async def event_update(event_id: str, patch: S.EventPatch) -> dict:
    """Change the fields of an Event that `patch` sets; also its team.

    `patch.version` is the `version` as last read; 409 `event_version_conflict` on a
    mismatch. The errors of `event_create` apply. The status changes with
    `event_set_status`.
    """
    return await api().patch(f"/events/{event_id}", json=dump_patch(patch))


@group.tool
async def event_set_status(event_id: str, status: S.OrderStatus, version: int) -> dict:
    """Set the status of an Event: a key of the list `event` (422 `status_unknown`).

    409 `event_version_conflict` on an old `version`.
    """
    return await api().post(
        f"/events/{event_id}/status", json={"status": status, "version": version}
    )


@group.tool
async def event_delete(event_id: str) -> dict:
    """Delete an Event; its links go with it."""
    return await api().delete(f"/events/{event_id}")


@group.tool
async def event_refs(q: str | None = None) -> list:
    """List the open Events that the caller writes: the Veranstaltung picker of a Buchung."""
    return await api().get("/events/refs", params=params(q=q))


@group.tool
async def event_series(q: str | None = None) -> list:
    """List the Reihen of Events by name (at most 50)."""
    return await api().get("/events/series", params=params(q=q))


@group.tool
async def event_series_create(name: str) -> dict:
    """Create a Reihe for Events; the name is unique, case ignored (409 `series_exists`)."""
    return await api().post("/events/series", json={"name": name})


@group.tool
async def export_events_xlsx(
    target_path: str,
    segment: EventSegment | None = None,
    team: str | None = None,
    series: str | None = None,
    q: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Export the event list as `.xlsx` to a local file. Requires `finance.export`.

    The filters work as in `event_list`.
    """
    return await download_to(
        "GET",
        "/events/export.xlsx",
        target_path,
        overwrite=overwrite,
        fallback="veranstaltungen.xlsx",
        query=_filter(segment, team, series, q),
    )


def register(mcp: FastMCP) -> None:
    """Register the event tools on the shared FastMCP instance."""
    group.register(mcp)
