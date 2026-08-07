"""Meeting-cycle tools for votes, meetings, protocols, delegations and attachments.

The group manages a vote but never casts one. It also covers the agenda and the
attendance of a meeting, the protocol (minutes), the delegations, and the application
attachments.

An agent can create, open, close and cancel a vote. There is deliberately no tool to
cast a ballot. Voting is human-only.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def get_vote(vote_id: str) -> dict:
    """Fetch the state and the aggregated tally of a vote.

    A secret vote exposes the counts only.
    """
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
    """Close a vote, tally it, and fire the result branch.

    The call gives a 409 while the quorum is not met. Collect more ballots or call
    `cancel_vote`. An agent manages a vote but cannot cast a ballot. Casting is
    human-only. Requires vote.manage.
    """
    return await api().post(f"/votes/{vote_id}/close")


@group.tool
async def cancel_vote(vote_id: str) -> dict:
    """Cancel an OPEN vote.

    The status becomes `cancelled`. There is no result and no flow branch. The
    application stays in its vote state. This is the way out when the quorum cannot be
    reached, because `close_vote` is blocked then. Requires vote.manage.
    """
    return await api().post(f"/votes/{vote_id}/cancel")


@group.tool
async def list_meetings() -> dict:
    """List the meetings."""
    return await api().get("/meetings")


@group.tool
async def get_meeting(meeting_id: str) -> dict:
    """Fetch one meeting with its agenda, its attendance and its votes."""
    return await api().get(f"/meetings/{meeting_id}")


@group.tool
async def create_meeting(meeting: S.MeetingCreate) -> dict:
    """Create a meeting. Requires meeting.manage."""
    return await api().post("/meetings", json=dump_create(meeting))


@group.tool
async def update_meeting(meeting_id: str, patch: S.MeetingPatch) -> dict:
    """Patch a meeting.

    The fields are `status` (planned, live or closed), `date`, `startTime`,
    `endTime`, `protokollantId` and `activeApplicationId`. Requires meeting.manage.
    """
    return await api().patch(f"/meetings/{meeting_id}", json=dump_patch(patch))


@group.tool
async def delete_meeting(meeting_id: str) -> dict:
    """Delete a meeting. Requires meeting.manage."""
    return await api().delete(f"/meetings/{meeting_id}")


@group.tool
async def get_attendance(meeting_id: str) -> dict:
    """Get the attendance list of a meeting: present, excused or absent per member."""
    return await api().get(f"/meetings/{meeting_id}/attendance")


@group.tool
async def set_attendance(
    meeting_id: str,
    principal_id: str,
    status: Literal["present", "excused", "absent"],
) -> dict:
    """Set the attendance of a member for a meeting. Requires meeting.manage."""
    return await api().put(
        f"/meetings/{meeting_id}/attendance/{principal_id}", json={"status": status}
    )


@group.tool
async def add_agenda_item(
    meeting_id: str,
    application_id: str | None = None,
    title: str | None = None,
) -> dict:
    """Add an agenda item to a meeting.

    Give EXACTLY ONE of `application_id` for an application item or `title` for a
    free-text item. Requires meeting.manage.
    """
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
    """Update an agenda item.

    The `body` sets the markdown text. The `title` renames a free-text item. An
    application item inherits its title. Requires meeting.manage.
    """
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
    """Reorder the agenda. Give `item_ids` in the desired order. Requires meeting.manage."""
    return await api().put(
        f"/meetings/{meeting_id}/agenda/order", json={"itemIds": item_ids}
    )


@group.tool
async def list_assignable_agenda_items(meeting_id: str) -> dict:
    """List the applications that you can add as agenda items to this meeting."""
    return await api().get(f"/meetings/{meeting_id}/agenda/assignable")


@group.tool
async def create_meeting_vote(meeting_id: str, vote: S.MeetingVoteOpenBody) -> dict:
    """Open a live vote on an agenda item of a meeting.

    The agenda item can be a free-text item or an application item.
    Requires vote.manage.
    """
    return await api().post(f"/meetings/{meeting_id}/votes", json=dump_create(vote))


@group.tool
async def delete_meeting_vote(meeting_id: str, vote_id: str) -> dict:
    """Delete a meeting vote. Requires vote.manage."""
    return await api().delete(f"/meetings/{meeting_id}/votes/{vote_id}")


@group.tool
async def get_or_create_protocol(meeting_id: str) -> dict:
    """Create OR load the protocol of a meeting.

    The call is idempotent. A meeting holds exactly one protocol.
    Requires meeting.manage.
    """
    return await api().post(f"/meetings/{meeting_id}/protocol")


@group.tool
async def update_protocol(protocol_id: str, markdown: str) -> dict:
    """Update the markdown body of a protocol.

    The call gives a 409 while the protocol is final or rendering.
    Requires meeting.manage.
    """
    return await api().patch(f"/protocols/{protocol_id}", json={"markdown": markdown})


@group.tool
async def embed_protocol_votes(protocol_id: str, vote_ids: list[str]) -> dict:
    """Append closed votes to the protocol as markdown snippets.

    The call is idempotent per vote. Requires meeting.manage.
    """
    return await api().post(
        f"/protocols/{protocol_id}/votes", json={"voteIds": vote_ids}
    )


@group.tool
async def finalize_protocol(protocol_id: str) -> dict:
    """Finalize the protocol.

    The call is ASYNC. It returns `status: "rendering"` while a worker renders the PDF
    and mails it to the Gremium. Re-fetch with `get_or_create_protocol(meeting_id)`
    until `status` is `final`. A fall back to `draft` means the render failed. Fix the
    content and finalize again. The call is idempotent. Requires meeting.manage.
    """
    return await api().post(f"/protocols/{protocol_id}/finalize")


@group.tool
async def list_delegations() -> dict:
    """List the meeting delegations: who delegates attendance and voting to whom."""
    return await api().get("/delegations")


@group.tool
async def create_delegation(delegation: S.DelegationCreate) -> dict:
    """Delegate attendance for a meeting to another member.

    The delegation can also transfer the vote.
    """
    return await api().post("/delegations", json=dump_create(delegation))


@group.tool
async def revoke_delegation(delegation_id: str) -> dict:
    """Revoke a delegation."""
    return await api().delete(f"/delegations/{delegation_id}")


@group.tool
async def list_substitutes() -> dict:
    """List the substitute pool of standing stand-ins per Gremium."""
    return await api().get("/delegations/substitutes")


@group.tool
async def create_substitute(substitute: S.SubstituteCreate) -> dict:
    """Add a stand-in to the substitute pool of a Gremium."""
    return await api().post("/delegations/substitutes", json=dump_create(substitute))


@group.tool
async def delete_substitute(substitute_id: str) -> dict:
    """Remove a stand-in from the substitute pool."""
    return await api().delete(f"/delegations/substitutes/{substitute_id}")


@group.tool
async def list_attachments(application_id: str) -> dict:
    """List the file attachments of an application.

    The call returns the metadata only. Upload and download stay with the UI and the
    REST API.
    """
    return await api().get(f"/applications/{application_id}/attachments")


@group.tool
async def delete_attachment(attachment_id: str) -> dict:
    """Delete a file attachment."""
    return await api().delete(f"/attachments/{attachment_id}")


def register(mcp: FastMCP) -> None:
    """Register the votes/meetings/protocol/delegations tool group."""
    group.register(mcp)
