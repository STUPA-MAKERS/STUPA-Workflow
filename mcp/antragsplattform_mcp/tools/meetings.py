"""Meeting-cycle tools: votes (manage, never cast), meetings/agenda/attendance,
protocol (minutes), delegations, and application attachments.

Agents can create/open/close/cancel votes but there is intentionally no tool to cast
a ballot — voting is human-only.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


# --- votes (manage, NOT cast)
@group.tool
async def get_vote(vote_id: str) -> dict:
    """Fetch a vote's state + aggregated tally (secret votes expose counts only)."""
    return await api().get(f"/votes/{vote_id}")


@group.tool
async def create_application_vote(application_id: str, vote: S.VoteCreate) -> dict:
    """Create a vote bound to an application. Requires vote.manage."""
    return await api().post(
        f"/applications/{application_id}/votes", json=dump_create(vote)
    )


@group.tool
async def open_vote(vote_id: str) -> dict:
    """Open a vote for balloting. Requires vote.manage."""
    return await api().post(f"/votes/{vote_id}/open")


@group.tool
async def close_vote(vote_id: str) -> dict:
    """Close a vote, tally it, fire the result branch. 409 while the quorum is
    not met — collect more ballots or cancel_vote. Requires vote.manage.
    (Agents manage votes but cannot cast ballots — that is human-only.)"""
    return await api().post(f"/votes/{vote_id}/close")


@group.tool
async def cancel_vote(vote_id: str) -> dict:
    """Cancel an OPEN vote: status becomes cancelled, no result, no flow branch —
    the application stays in its vote state. The way out when the quorum cannot
    be reached (close is blocked then). Requires vote.manage."""
    return await api().post(f"/votes/{vote_id}/cancel")


# --- meetings
@group.tool
async def list_meetings() -> dict:
    """List meetings."""
    return await api().get("/meetings")


@group.tool
async def get_meeting(meeting_id: str) -> dict:
    """Fetch one meeting (agenda, attendance, votes)."""
    return await api().get(f"/meetings/{meeting_id}")


@group.tool
async def create_meeting(meeting: S.MeetingCreate) -> dict:
    """Create a meeting. Requires meeting.manage."""
    return await api().post("/meetings", json=dump_create(meeting))


@group.tool
async def update_meeting(meeting_id: str, patch: S.MeetingPatch) -> dict:
    """Patch a meeting (status planned|live|closed, date, startTime, protokollantId,
    activeApplicationId). Requires meeting.manage."""
    return await api().patch(f"/meetings/{meeting_id}", json=dump_patch(patch))


@group.tool
async def delete_meeting(meeting_id: str) -> dict:
    """Delete a meeting. Requires meeting.manage."""
    return await api().delete(f"/meetings/{meeting_id}")


@group.tool
async def get_attendance(meeting_id: str) -> dict:
    """Attendance list of a meeting (present/excused/absent per member)."""
    return await api().get(f"/meetings/{meeting_id}/attendance")


@group.tool
async def set_attendance(
    meeting_id: str,
    principal_id: str,
    status: Literal["present", "excused", "absent"],
) -> dict:
    """Set a member's attendance for a meeting. Requires meeting.manage."""
    return await api().put(
        f"/meetings/{meeting_id}/attendance/{principal_id}", json={"status": status}
    )


@group.tool
async def add_agenda_item(
    meeting_id: str,
    application_id: str | None = None,
    title: str | None = None,
) -> dict:
    """Add an agenda item (TOP): EXACTLY ONE of application_id (application TOP) or
    title (free-text TOP). Requires meeting.manage."""
    return await api().post(
        f"/meetings/{meeting_id}/agenda",
        json=params(applicationId=application_id, title=title),
    )


@group.tool
async def update_agenda_item(
    meeting_id: str,
    item_id: str,
    body: str | None = None,
    title: str | None = None,
) -> dict:
    """Update an agenda item: `body` sets the markdown text; `title` renames a
    free-text TOP (application TOPs inherit their title). Requires meeting.manage."""
    return await api().patch(
        f"/meetings/{meeting_id}/agenda/{item_id}",
        json=params(body=body, title=title),
    )


@group.tool
async def delete_agenda_item(meeting_id: str, item_id: str) -> dict:
    """Remove an agenda item from a meeting. Requires meeting.manage."""
    return await api().delete(f"/meetings/{meeting_id}/agenda/{item_id}")


@group.tool
async def reorder_agenda(meeting_id: str, item_ids: list[str]) -> dict:
    """Reorder the agenda: item_ids in the desired order. Requires meeting.manage."""
    return await api().put(
        f"/meetings/{meeting_id}/agenda/order", json={"itemIds": item_ids}
    )


@group.tool
async def list_assignable_agenda_items(meeting_id: str) -> dict:
    """Applications available to be added as agenda items for this meeting."""
    return await api().get(f"/meetings/{meeting_id}/agenda/assignable")


@group.tool
async def create_meeting_vote(meeting_id: str, vote: S.MeetingVoteOpenBody) -> dict:
    """Open a live vote within a meeting on an agenda item (generic TOP or
    application-bound). Requires vote.manage."""
    return await api().post(f"/meetings/{meeting_id}/votes", json=dump_create(vote))


@group.tool
async def delete_meeting_vote(meeting_id: str, vote_id: str) -> dict:
    """Delete a meeting vote. Requires vote.manage."""
    return await api().delete(f"/meetings/{meeting_id}/votes/{vote_id}")


# --- protocol (minutes)
@group.tool
async def get_or_create_protocol(meeting_id: str) -> dict:
    """Create OR load the meeting's protocol (idempotent, 1:1 per meeting).
    Requires meeting.manage."""
    return await api().post(f"/meetings/{meeting_id}/protocol")


@group.tool
async def update_protocol(protocol_id: str, markdown: str) -> dict:
    """Update the protocol's markdown body. 409 while it is final or rendering.
    Requires meeting.manage."""
    return await api().patch(f"/protocols/{protocol_id}", json={"markdown": markdown})


@group.tool
async def embed_protocol_votes(protocol_id: str, vote_ids: list[str]) -> dict:
    """Append closed votes as markdown snippets to the protocol (idempotent per vote).
    Requires meeting.manage."""
    return await api().post(
        f"/protocols/{protocol_id}/votes", json={"voteIds": vote_ids}
    )


@group.tool
async def finalize_protocol(protocol_id: str) -> dict:
    """Finalize the protocol: ASYNC — returns `status: "rendering"` while a worker
    renders the PDF and mails it to the committee. Re-fetch via
    `get_or_create_protocol(meeting_id)` until `status` is `final`; a fall back to
    `draft` means the render failed (fix content, finalize again). Idempotent.
    Requires meeting.manage."""
    return await api().post(f"/protocols/{protocol_id}/finalize")


# --- delegations
@group.tool
async def list_delegations() -> dict:
    """List meeting delegations (who delegates attendance/voting to whom)."""
    return await api().get("/delegations")


@group.tool
async def create_delegation(delegation: S.DelegationCreate) -> dict:
    """Delegate attendance (and optionally voting) for a meeting to another member."""
    return await api().post("/delegations", json=dump_create(delegation))


@group.tool
async def revoke_delegation(delegation_id: str) -> dict:
    """Revoke a delegation."""
    return await api().delete(f"/delegations/{delegation_id}")


@group.tool
async def list_substitutes() -> dict:
    """List the substitute pool (standing stand-ins per committee)."""
    return await api().get("/delegations/substitutes")


@group.tool
async def create_substitute(substitute: S.SubstituteCreate) -> dict:
    """Add a stand-in to a committee's substitute pool."""
    return await api().post("/delegations/substitutes", json=dump_create(substitute))


@group.tool
async def delete_substitute(substitute_id: str) -> dict:
    """Remove a stand-in from the substitute pool."""
    return await api().delete(f"/delegations/substitutes/{substitute_id}")


# --- attachments (metadata only)
@group.tool
async def list_attachments(application_id: str) -> dict:
    """List an application's file attachments (metadata only — up/download is
    UI/REST territory)."""
    return await api().get(f"/applications/{application_id}/attachments")


@group.tool
async def delete_attachment(attachment_id: str) -> dict:
    """Delete a file attachment."""
    return await api().delete(f"/attachments/{attachment_id}")


def register(mcp: FastMCP) -> None:
    """Register the votes/meetings/protocol/delegations tool group."""
    group.register(mcp)
