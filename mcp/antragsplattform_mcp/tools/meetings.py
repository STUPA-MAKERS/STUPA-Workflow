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

    A secret vote exposes the counts only. `openedAt` and `closedAt` are the real open
    and end times; `closesAt` is the planned end of the cast window. `myBallot`
    (`cast`, `choice`) is the own ballot of the caller; a secret vote gives no choice.
    `representedCast` tells whether the caller cast the ballot of a delegator.
    """
    return await api().get(f"/votes/{vote_id}")


@group.tool
async def create_application_vote(application_id: str, vote: S.VoteCreate) -> dict:
    """Create a vote bound to an application.

    `eligibleGroup` is the UUID of the gremium of the application. The server counts
    the eligible voters. Requires the gremium permission `vote.manage` or
    `session.manage` in that gremium (or admin). If the application and its state name
    no gremium, only admin can create the vote (403).
    """
    return await api().post(
        f"/applications/{application_id}/votes", json=dump_create(vote)
    )


@group.tool
async def open_vote(vote_id: str) -> dict:
    """Open a vote for balloting.

    Requires the gremium permission `vote.manage` or `session.manage` in the gremium of
    the vote (or admin).
    """
    return await api().post(f"/votes/{vote_id}/open")


@group.tool
async def close_vote(vote_id: str) -> dict:
    """Close a vote, tally it, and fire the result branch.

    The call gives a 409 while the quorum is not met. Collect more ballots or call
    `cancel_vote`. The close always ends the vote. `branchFired` is false when the pass
    or fail transition did not fire (its guard failed, or the state has no such
    transition). The audit log then holds `vote_branch_blocked`, and the application
    stays in the vote state. `fire_transition` cannot fire a pass or fail transition
    (409), because only the vote outcome fires it. A person with
    `application.force_status` moves the application with "Set status" (force status),
    or fires a manual exit of the vote state that is not a branch, if the flow has one.
    An agent manages a vote but cannot cast a ballot. Casting is human-only. Requires
    the gremium permission `vote.manage` or `session.manage` in the gremium of the vote
    (or admin).
    """
    return await api().post(f"/votes/{vote_id}/close")


@group.tool
async def cancel_vote(vote_id: str) -> dict:
    """Cancel an OPEN vote.

    The status becomes `cancelled`. There is no result and no flow branch. The
    application stays in its vote state. This is the way out when the quorum cannot be
    reached, because `close_vote` is blocked then. Requires the gremium permission
    `vote.manage` or `session.manage` in the gremium of the vote (or admin).
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
    """Create a meeting. Requires session.manage in the target gremium (or admin)."""
    return await api().post("/meetings", json=dump_create(meeting))


@group.tool
async def update_meeting(meeting_id: str, patch: S.MeetingPatch) -> dict:
    """Patch a meeting.

    The fields are `status` (planned, live or closed), `date`, `startTime`,
    `protokollantId` and `activeApplicationId`. Date, time and minute-taker need
    session.manage in the meeting's gremium (or admin). Status and active application
    need write access (session.manage or protocol.write in the gremium, or the
    assigned minute-taker).

    The status runs only planned -> live -> closed. A repeat of the current status
    changes nothing. Every other change gives 409 `invalid_status_transition`: a
    meeting never goes back, and a meeting that does not take place is deleted
    (`delete_meeting`), not closed. The start needs a minute-taker and sets
    `startedAt`. The close gives 409 `open_vote` while a vote of the meeting is open
    (close or cancel it first), and it cancels the draft votes. A closed meeting
    keeps its date, time and minute-taker.

    A new minute-taker needs protocol.write in the gremium (422
    `protokollant_needs_protocol_write`). While the meeting is live, a new
    minute-taker is a handover with mode `now` (see `protokollant_handover`). The
    same minute-taker again changes nothing.
    """
    return await api().patch(f"/meetings/{meeting_id}", json=dump_patch(patch))


@group.tool
async def protokollant_handover(
    meeting_id: str,
    principal_id: str,
    mode: Literal["now", "next_item"] = "now",
) -> dict:
    """Hand the minutes of a LIVE meeting over to another member.

    `now` hands over at once: the running period of the minute-taker ends and the
    next one starts. `next_item` plans the handover: the next forward move of the
    current agenda item starts it. A new plan replaces the old one. The rights that
    follow the minute-taker move with the handover (agenda item change and votes).

    Callers: session.manage in the meeting's gremium (or admin), or the current
    minute-taker. The new minute-taker must be an active member (403) with
    protocol.write in the gremium (422 `protokollant_needs_protocol_write`). 409
    `meeting_not_live` outside a live meeting, `already_protokollant` for the current
    minute-taker, `no_next_item` for `next_item` on the last agenda item. Every
    handover goes into the audit log (`protokollant_handover`). Returns the meeting
    with `keeperPeriods` and `plannedHandover`.
    """
    return await api().post(
        f"/meetings/{meeting_id}/protokollant-handover",
        json={"principalId": principal_id, "mode": mode},
    )


@group.tool
async def cancel_protokollant_handover(meeting_id: str) -> dict:
    """Discard the planned handover (`next_item`) of a live meeting.

    Same callers as `protokollant_handover`. 404 `no_planned_handover` without a
    plan. Goes into the audit log. Returns the meeting.
    """
    return await api().delete(f"/meetings/{meeting_id}/protokollant-handover")


@group.tool
async def delete_meeting(meeting_id: str) -> dict:
    """Delete a meeting. Requires session.manage in the meeting's gremium (or admin).

    This is also the way to cancel a planned meeting that does not take place. A
    meeting with a final protocol also needs `meeting.delete_finalized`. A meeting
    with an open vote does not delete (409 `open_vote`): close or cancel the vote
    first. The delete cancels the draft votes. The other votes of the meeting and
    their ballots stay.
    """
    return await api().delete(f"/meetings/{meeting_id}")


@group.tool
async def get_attendance(meeting_id: str) -> dict:
    """Get the attendance list of a meeting: present, excused or absent per member.

    `status` null means "open" (nothing recorded). `source` is `self` (the member
    reported it) or `lead` (the meeting lead set it). `note` is the reason of an
    excuse. Only the member and the meeting lead see it; it is null for all others.
    """
    return await api().get(f"/meetings/{meeting_id}/attendance")


@group.tool
async def set_attendance(
    meeting_id: str,
    principal_id: str,
    status: Literal["present", "excused", "absent"],
    note: str | None = None,
) -> dict:
    """Set the attendance of a member for a meeting as the meeting lead.

    Requires write access to the meeting: session.manage or protocol.write in its
    gremium, the assigned minute-taker, or admin. Rules:
    - Only while the meeting is planned or live; a closed meeting gives 409.
    - The lead's value wins: the member can no longer change it until the lead
      resets it with `reset_attendance`.
    - `present` gives 409 `delegation_active` while the member has a delegation for
      this meeting. Revoke the delegation first. After the meeting start, the
      meeting lead (session.manage) can revoke it while the meeting is live, and an
      admin at any time.
    - `note` (the reason, max. 500 characters) is allowed only with `excused`.
      Without `note` an excused member keeps the stored reason.
    The change goes into the audit log (`attendance_set`), without the note.
    """
    body: dict[str, str] = {"status": status}
    if note is not None:
        body["note"] = note
    return await api().put(
        f"/meetings/{meeting_id}/attendance/{principal_id}", json=body
    )


@group.tool
async def reset_attendance(meeting_id: str, principal_id: str) -> dict:
    """Reset the attendance of a member to "open" as the meeting lead.

    Deletes the record, so the member can report the own attendance again.
    Same access and state rules as `set_attendance`; a closed meeting gives 409.
    The reset goes into the audit log (`attendance_reset`). Returns the roster.
    """
    return await api().delete(f"/meetings/{meeting_id}/attendance/{principal_id}")


@group.tool
async def add_agenda_item(
    meeting_id: str,
    application_id: str | None = None,
    title: str | None = None,
) -> dict:
    """Add an agenda item to a meeting.

    Give EXACTLY ONE of `application_id` for an application item or `title` for a
    free-text item. Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin. Only a
    planned or live meeting takes a new item; a closed meeting gives 409
    `meeting_closed`.
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
    application item inherits its title. Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin.

    The `body` needs a live meeting, or a closed meeting whose protocol is still a
    draft (409 `meeting_not_started` or `protocol_locked` otherwise). The `title`
    needs a planned or live meeting (409 `meeting_closed` otherwise).
    """
    return await api().patch(
        f"/meetings/{meeting_id}/agenda/{item_id}",
        json=params(body=body, title=title),
    )


@group.tool
async def delete_agenda_item(meeting_id: str, item_id: str) -> dict:
    """Remove an agenda item from a meeting.

    Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin. Only a
    planned or live meeting removes an item (409 `meeting_closed` otherwise). An item
    with an open or closed vote stays (409 `agenda_item_has_vote`). Its draft and
    cancelled votes are deleted with it. To delete these votes you also need the
    vote right of the meeting (manager, minute-taker or gremium vote.manage), else
    403.
    """
    return await api().delete(f"/meetings/{meeting_id}/agenda/{item_id}")


@group.tool
async def reorder_agenda(meeting_id: str, item_ids: list[str]) -> dict:
    """Reorder the agenda. Give `item_ids` in the desired order.

    Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin. Only a
    planned or live meeting changes its order (409 `meeting_closed` otherwise).
    """
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

    The agenda item can be a free-text item or an application item. The gremium of the
    meeting votes, and the server counts its eligible voters. Requires the lead of the
    meeting, the minute-taker, or the gremium permission `vote.manage`.
    """
    return await api().post(f"/meetings/{meeting_id}/votes", json=dump_create(vote))


@group.tool
async def delete_meeting_vote(meeting_id: str, vote_id: str) -> dict:
    """Delete a meeting vote.

    Requires the lead of the meeting, the minute-taker, or the gremium permission
    `vote.manage`. Only a planned or live meeting deletes a vote; after the close the
    vote is part of the record (409 `meeting_closed`). Only a draft or cancelled vote
    can go; an open or closed vote gives 409 `vote_not_deletable` (cancel an open vote
    first). Every delete is audited.
    """
    return await api().delete(f"/meetings/{meeting_id}/votes/{vote_id}")


@group.tool
async def get_or_create_protocol(meeting_id: str) -> dict:
    """Create OR load the protocol of a meeting.

    The call is idempotent. A meeting holds exactly one protocol.
    Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin.
    """
    return await api().post(f"/meetings/{meeting_id}/protocol")


@group.tool
async def update_protocol(protocol_id: str, markdown: str) -> dict:
    """Update the markdown body of a protocol.

    The call gives a 409 while the protocol is final or rendering.
    Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin.
    """
    return await api().patch(f"/protocols/{protocol_id}", json={"markdown": markdown})


@group.tool
async def embed_protocol_votes(protocol_id: str, vote_ids: list[str]) -> dict:
    """Append closed votes to the protocol as markdown snippets.

    The call is idempotent per vote. Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin. Only the
    votes of the protocol's own meeting: any other vote gives 422 `vote_not_in_meeting`.
    """
    return await api().post(
        f"/protocols/{protocol_id}/votes", json={"voteIds": vote_ids}
    )


@group.tool
async def finalize_protocol(protocol_id: str) -> dict:
    """Finalize the protocol.

    Only after the meeting is CLOSED (409 `meeting_not_closed` before), and only
    once: a protocol that is rendering or final gives 409 `protocol_not_draft`.

    The call is ASYNC. It returns `status: "rendering"` while a worker renders the PDF
    and mails it to the Gremium. Re-fetch with `get_or_create_protocol(meeting_id)`
    until `status` is `final`. A fall back to `draft` means the render failed. Fix the
    content and finalize again. Requires the write access to the meeting AND the
    gremium permission protocol.finalize in its gremium (or admin). The start goes
    into the audit log (`protocol_finalize`).
    """
    return await api().post(f"/protocols/{protocol_id}/finalize")


@group.tool
async def list_delegations() -> dict:
    """List the meeting delegations: who delegates attendance and voting to whom."""
    return await api().get("/delegations")


@group.tool
async def create_delegation(delegation: S.DelegationCreate) -> dict:
    """Delegate attendance for a meeting to another member.

    The delegation can also transfer the vote. Without `delegatorId` the caller
    delegates for themselves while the meeting is planned. With `delegatorId` the
    meeting lead (session.manage in the gremium) enters a substitution for a missing
    member (no attendance record, excused or absent) while the meeting is live. The
    delegate must then be a substitute of the member's faculty group.
    """
    return await api().post("/delegations", json=dump_create(delegation))


@group.tool
async def revoke_delegation(delegation_id: str) -> dict:
    """Revoke a delegation.

    The delegator can revoke before the meeting start. The meeting lead can revoke
    while the meeting is live; a ballot that the delegate already cast stays.
    """
    return await api().delete(f"/delegations/{delegation_id}")


@group.tool
async def list_substitutes(gremium_id: str) -> dict:
    """List the substitute pool (personal and gremium-wide stand-ins) of one Gremium."""
    return await api().get("/delegations/substitutes", params=params(gremiumId=gremium_id))


@group.tool
async def list_substitute_groups(gremium_id: str) -> dict:
    """List the faculty substitute groups of one Gremium with members and substitutes.

    A substitute of a group may represent every member of that group without the
    lead-time deadline. A member counts only while the gremium membership is active
    (`active`). `tooManySubstitutes` warns above two substitutes; it is no limit.
    """
    return await api().get(
        "/delegations/substitute-groups", params=params(gremiumId=gremium_id)
    )


@group.tool
async def create_substitute_group(group: S.SubstituteGroupCreate) -> dict:
    """Create a faculty substitute group in a Gremium.

    Requires admin.delegations or session.manage in the gremium.
    """
    return await api().post("/delegations/substitute-groups", json=dump_create(group))


@group.tool
async def update_substitute_group(group_id: str, patch: S.SubstituteGroupUpdate) -> dict:
    """Rename a faculty substitute group or change its position."""
    return await api().patch(
        f"/delegations/substitute-groups/{group_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_substitute_group(group_id: str) -> dict:
    """Delete a faculty substitute group with its members and substitutes."""
    return await api().delete(f"/delegations/substitute-groups/{group_id}")


@group.tool
async def add_substitute_group_member(
    group_id: str, principal_id: str, kind: Literal["member", "substitute"]
) -> dict:
    """Add a person to a faculty substitute group as a member or as a substitute.

    A member is in at most one group per Gremium (409 otherwise). A substitute may
    be in several groups.
    """
    return await api().post(
        f"/delegations/substitute-groups/{group_id}/members",
        json={"principalId": principal_id, "kind": kind},
    )


@group.tool
async def remove_substitute_group_member(group_id: str, principal_id: str) -> dict:
    """Remove a person from a faculty substitute group."""
    return await api().delete(
        f"/delegations/substitute-groups/{group_id}/members/{principal_id}"
    )


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
