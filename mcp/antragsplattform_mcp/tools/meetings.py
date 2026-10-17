"""Meeting-cycle tools for votes, meetings, protocols, delegations and attachments.

The group manages a vote but never casts one. It also covers the agenda and the
attendance of a meeting, the protocol (minutes), the delegations, and the application
attachments (list, upload from a local file, download to a local file, delete). The
download also serves the files of chat messages.

An agent can create, open, close and cancel a vote. There is deliberately no tool to
cast a ballot. Voting is human-only.
"""

from __future__ import annotations

import codecs
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..client import ApiError
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

    A personnel election has `kind: "election"`, the candidates in `election` and,
    after the close, `electionResult` (`counts` per candidate id, `abstentions`,
    `elected`, and `runoff` or `lot` when a tie stays open). Its `result` is
    `elected`, `runoff`, `tie` (the lot is pending) or `rejected`. `myBallot.choices`
    holds the own candidate ids of an open election.
    """
    return await api().get(f"/votes/{vote_id}")


@group.tool
async def vote_draw_lot(vote_id: str) -> dict:
    """Draw the lot for a closed personnel election that ended in a tie.

    The server draws the open seats among the tied candidates and records who drew the
    lot. 409 `no_lot_pending` when the result is not `tie`, 409 `lot_already_drawn` on
    a second call, 409 `not_an_election` for a motion. Requires the gremium permission
    `vote.manage` or `session.manage` in the gremium of the vote (or admin). Audited.
    """
    return await api().post(f"/votes/{vote_id}/draw-lot")


@group.tool
async def vote_runoff(vote_id: str) -> dict:
    """Create the runoff (Stichwahl) of a closed personnel election.

    Only when the result is `runoff`: the new draft vote has the tied candidates and the
    open seats, round + 1 and `parentVoteId`. Open it with `open_vote`. The meeting must
    be live. 409 `no_runoff_pending` or `runoff_exists`. Requires the gremium
    permission `vote.manage` or `session.manage` (or admin).
    """
    return await api().post(f"/votes/{vote_id}/runoff")


@group.tool
async def create_application_vote(application_id: str, vote: S.VoteCreate) -> dict:
    """Create a vote bound to an application.

    `eligibleGroup` is the UUID of the gremium of the application. The server counts
    the eligible voters. Requires the gremium permission `vote.manage` or
    `session.manage` in that gremium (or admin). If the application and its state name
    no gremium, only admin can create the vote (403).

    `proposal` (approved amount and conditions) becomes the decision of the
    application when the vote passes.
    """
    return await api().post(
        f"/applications/{application_id}/votes", json=dump_create(vote)
    )


@group.tool
async def open_vote(vote_id: str) -> dict:
    """Open a vote for balloting.

    Requires the gremium permission `vote.manage` or `session.manage` in the gremium of
    the vote (or admin). A vote on an application in a vote state opens only when its
    gremium decides that state (`voteGremiumId`), else 409 `vote_gremium_mismatch`.
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

    The fields are `status` (planned, live or closed), `title`, `date`, `startTime`,
    `protokollantId` and `activeApplicationId`. Title, date, time and minute-taker need
    session.manage in the meeting's gremium (or admin). Status and active application
    need write access (session.manage or protocol.write in the gremium, or the
    assigned minute-taker).

    The status runs only planned -> live -> closed. A repeat of the current status
    changes nothing. Every other change gives 409 `invalid_status_transition`: a
    meeting never goes back, and a meeting that does not take place is deleted
    (`delete_meeting`), not closed. The start needs a minute-taker and sets
    `startedAt`. The close gives 409 `open_vote` while a vote of the meeting is open
    (close or cancel it first), and it cancels the draft votes. A closed meeting
    keeps its title, date, time and minute-taker.

    The start has an open window (`opensAt`, `confirmUntil` on the meeting): before
    `opensAt` it gives 409 `meeting_too_early`, and before `confirmUntil` it needs
    `confirmEarly: true` (else 409 `early_open_unconfirmed`). Ask the user before you
    confirm an early open.

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
    """Open a live vote on an agenda item of a meeting, or prepare it as a draft.

    With `draft: true` the vote is only prepared: it stays a draft, also in a planned
    meeting, until `open_meeting_vote` opens it. Without it the meeting must be live.
    The agenda item can be a free-text item or an application item. The gremium of the
    meeting votes, and the server counts its eligible voters. Requires the lead of the
    meeting, the minute-taker, or the gremium permission `vote.manage`. An application
    item needs the application in a vote state that the gremium of the meeting decides
    (`voteGremiumId`), else 409 `vote_gremium_mismatch`.

    In a public meeting where guests vote, `guestsVote` (default on for a public item)
    lets the admitted guests vote too: such a vote has no quorum, the majority of the
    cast ballots decides.

    On an application item, `proposal` (approved amount and conditions) becomes the
    decision of the application when the vote passes.
    With `kind: "election"`, `seats` and `candidates` the call opens a personnel
    election on a free-text item. It is secret by default; guests vote only when
    `guestsVote` is true.
    """
    return await api().post(f"/meetings/{meeting_id}/votes", json=dump_create(vote))


@group.tool
async def open_meeting_vote(meeting_id: str, vote_id: str) -> dict:
    """Open a prepared draft vote of a live meeting.

    The same callers as for `create_meeting_vote`. The server checks the application
    and the guests again and counts the eligible voters from the current roster. 409
    `meeting_not_started` before the start, 409 `guests_vote_unavailable` when guests
    no longer vote on the question.
    """
    return await api().post(f"/meetings/{meeting_id}/votes/{vote_id}/open")


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


# Public meeting with a QR code (#17). The meeting lead (session.manage in the gremium,
# or admin) decides on the join requests. Guests vote themselves on their phones; no
# tool casts a ballot.


@group.tool
async def list_meeting_guests(meeting_id: str) -> list[dict]:
    """List the join requests and the guests of a public meeting.

    The open requests (`pending`) come first. `displayName` is null once a guest is
    pseudonymized ("Gast {number}"). Requires session.manage in the meeting's gremium.
    """
    return await api().get(f"/meetings/{meeting_id}/guests")


@group.tool
async def admit_meeting_guest(meeting_id: str, guest_id: str) -> dict:
    """Admit a waiting guest (409 `guest_not_pending` otherwise).

    A guest admitted while a vote with guests is open votes in it too. Audited
    (`guest_admitted`, ids only).
    """
    return await api().post(f"/meetings/{meeting_id}/guests/{guest_id}/admit")


@group.tool
async def reject_meeting_guest(meeting_id: str, guest_id: str) -> dict:
    """Reject a waiting guest. The device may ask again after 3 minutes."""
    return await api().post(f"/meetings/{meeting_id}/guests/{guest_id}/reject")


@group.tool
async def remove_meeting_guest(meeting_id: str, guest_id: str) -> dict:
    """Remove an admitted guest (409 `guest_not_admitted` otherwise).

    The guest can no longer vote; the ballots already cast stay counted.
    """
    return await api().post(f"/meetings/{meeting_id}/guests/{guest_id}/remove")


@group.tool
async def rename_meeting_guest(meeting_id: str, guest_id: str, display_name: str) -> dict:
    """Give a guest another name (2 to 80 characters).

    A pseudonymized guest gives 409 `guest_pseudonymized`. The audit entry holds the
    guest id only, never the name.
    """
    return await api().post(
        f"/meetings/{meeting_id}/guests/{guest_id}/rename",
        json={"displayName": display_name},
    )


@group.tool
async def admit_all_meeting_guests(meeting_id: str) -> list[dict]:
    """Admit every waiting guest at once. Returns the newly admitted guests."""
    return await api().post(f"/meetings/{meeting_id}/guests/admit-all")


@group.tool
async def get_meeting_join_link(meeting_id: str) -> dict:
    """Get the join link of a public meeting: `joinCode`, `joinUrl` and the QR matrix.

    409 `meeting_not_public` while public participation is off.
    """
    return await api().get(f"/meetings/{meeting_id}/join-link")


@group.tool
async def rotate_meeting_join_code(meeting_id: str) -> dict:
    """Replace the join code of a public meeting.

    The old link stops working and the open requests become void; the admitted guests
    stay. Audited (`meeting_join_code_rotated`).
    """
    return await api().post(f"/meetings/{meeting_id}/join-code/rotate")


@group.tool
async def get_or_create_protocol(meeting_id: str) -> dict:
    """Create OR load the protocol of a meeting.

    The call is idempotent. A meeting holds exactly one protocol.
    Requires write access to the meeting: session.manage
    or protocol.write in its gremium, the assigned minute-taker, or admin.
    """
    return await api().post(f"/meetings/{meeting_id}/protocol")


@group.tool
async def update_protocol(
    protocol_id: str,
    markdown: str | None = None,
    public_withheld: bool | None = None,
) -> dict:
    """Update the markdown body of a protocol, or hold it back from the public page.

    Send at least one of the two. `markdown` gives a 409 while the protocol is final
    or rendering, and requires write access to the meeting: session.manage or
    protocol.write in its gremium, the assigned minute-taker, or admin.

    `public_withheld=True` holds back this protocol from the public protocols page of
    a public Gremium; `False` releases it. It works also on a final protocol, needs
    the gremium permission protocol.finalize (or admin), and goes into the audit log
    (`protocol_publication`).
    """
    body: dict[str, object] = {}
    if markdown is not None:
        body["markdown"] = markdown
    if public_withheld is not None:
        body["publicWithheld"] = public_withheld
    return await api().patch(f"/protocols/{protocol_id}", json=body)


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
async def finalize_protocol(protocol_id: str, public_withheld: bool | None = None) -> dict:
    """Finalize the protocol.

    Only after the meeting is CLOSED (409 `meeting_not_closed` before), and only
    once: a protocol that is rendering or final gives 409 `protocol_not_draft`.

    The call is ASYNC. It returns `status: "rendering"` while a worker renders the PDF
    and mails it to the Gremium. Re-fetch with `get_or_create_protocol(meeting_id)`
    until `status` is `final`. A fall back to `draft` means the render failed. Fix the
    content and finalize again. Requires the write access to the meeting AND the
    gremium permission protocol.finalize in its gremium (or admin). The start goes
    into the audit log (`protocol_finalize`).

    In a Gremium that publishes its protocols, the final protocol appears on the
    public protocols page (public TOPs only, attendance as counts). Pass
    `public_withheld=True` to hold it back or `False` to release it; leave it out to
    keep the stored value (a draft held back with `update_protocol` stays held back).
    `update_protocol` can change it later.
    """
    body = {} if public_withheld is None else {"publicWithheld": public_withheld}
    return await api().post(f"/protocols/{protocol_id}/finalize", json=body)


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
    delegate must then be in the substitute pool of the gremium for that member: a
    personal entry for the member or a gremium-wide entry. The lead cannot name
    themselves as the delegate.
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
async def create_substitute(substitute: S.SubstituteCreate) -> dict:
    """Add a stand-in to the substitute pool of a Gremium."""
    return await api().post("/delegations/substitutes", json=dump_create(substitute))


@group.tool
async def delete_substitute(substitute_id: str) -> dict:
    """Remove a stand-in from the substitute pool."""
    return await api().delete(f"/delegations/substitutes/{substitute_id}")


# The upload allowlist of the platform (`backend/app/modules/files/mime.py`,
# `_EXT_TO_MIME`): file extension to the content type that the tool sends. The server
# sniffs the bytes with libmagic and ignores the claimed type, but it rejects a file
# whose sniffed type does not match the extension (415). The tool checks the extension
# first, so an agent gets the list of allowed types instead of a bare 415.
# `test_attachment_tools.py` compares this map with the backend when the backend imports.
ATTACHMENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}

# The hard cap of the platform (`MAX_ATTACHMENT_BYTES`). An instance can set a lower
# `attachment_max_bytes`; the server then answers 413.
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024

_DOWNLOAD_CHUNK = 64 * 1024
_DISPOSITION_PARAM = re.compile(
    r';\s*([!#$%&\'*+.^_`|~0-9A-Za-z-]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)'
)
_DISPOSITION_EXT_VALUE = re.compile(r"([A-Za-z0-9!#$%&+^_`{}~-]+)'[^']*'(.*)", re.DOTALL)
_DISPOSITION_CHARSETS = frozenset({"utf-8", "iso8859-1"})
_NAME_MAX_BYTES = 255
"""The longest file name in bytes on Linux, macOS and Windows file systems (NAME_MAX)."""


def _disposition_params(header: str) -> dict[str, str]:
    """Split the parameters of a `Content-Disposition` header into a dict.

    A quoted value is read as one token, so a `filename*=` or a `;` inside the quoted
    `filename` fallback is part of that value and never a parameter of its own. The
    file name of an upload reaches the fallback, so a search over the raw header would
    let an uploader pick the name that the tool saves the file under. The first
    occurrence of a parameter wins.
    """
    params: dict[str, str] = {}
    for match in _DISPOSITION_PARAM.finditer(header):
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = re.sub(r"\\(.)", r"\1", value[1:-1])
        params.setdefault(match.group(1).lower(), value)
    return params


def _decode_ext_value(value: str) -> str:
    """Decode an RFC 5987 `charset'lang'value`, or return `""`.

    Only UTF-8 and ISO-8859-1 are accepted, the two charsets that RFC 5987 names.
    """
    match = _DISPOSITION_EXT_VALUE.fullmatch(value)
    if match is None:
        return ""
    try:
        charset = codecs.lookup(match.group(1)).name
    except LookupError:
        return ""
    if charset not in _DISPOSITION_CHARSETS:
        return ""
    try:
        return unquote(match.group(2), encoding=charset, errors="strict")
    except UnicodeDecodeError:
        return ""


def _fit_name_max(name: str) -> str:
    """Shorten a name to `_NAME_MAX_BYTES` in UTF-8 and keep a short extension.

    The server allows 200 characters, which can be 800 bytes in UTF-8. A longer name
    makes the final rename fail with `ENAMETOOLONG`.
    """
    if len(name.encode()) <= _NAME_MAX_BYTES:
        return name
    stem, ext = os.path.splitext(name)
    if len(ext.encode()) > 32:
        stem, ext = name, ""
    while stem and len((stem + ext).encode()) > _NAME_MAX_BYTES:
        stem = stem[:-1]
    return stem + ext if stem else ""


def _disposition_filename(header: str) -> str:
    """Read the file name from a `Content-Disposition` header, without path parts.

    The server sends an ASCII `filename` fallback and the exact name as
    `filename*=UTF-8''<percent-encoded>` (RFC 6266, RFC 5987). The extended form wins,
    so `Einführung €.pdf` keeps its umlaut and its euro sign. A value that does not
    decode falls back to the plain `filename`. The result is the last path component
    only, at most 255 bytes in UTF-8, or `""` when there is none.
    """
    params = _disposition_params(header)
    name = _decode_ext_value(params.get("filename*", ""))
    if not name:
        name = params.get("filename", "")
    name = Path(name.replace("\\", "/")).name
    return "" if name in {".", ".."} else _fit_name_max(name)


def _attachment_part(
    file_path: str, filename: str | None
) -> tuple[str, bytes, str]:
    """Read a local file for the upload and pick its name and content type.

    Raises:
        ApiError: The file is missing, unreadable, empty, too large, or its extension
            is not on the allowlist (status 400; nothing is sent).
    """
    p = Path(file_path).expanduser()
    if not p.is_file():
        raise ApiError(400, f"file not found: {file_path!r}")
    if not os.access(p, os.R_OK):
        raise ApiError(400, f"file not readable: {file_path!r}")
    name = Path(filename).name if filename else p.name
    ext = Path(name).suffix.lower()
    mime = ATTACHMENT_TYPES.get(ext)
    if mime is None:
        allowed = ", ".join(ATTACHMENT_TYPES)
        raise ApiError(
            400, f"file type {ext or '(none)'!r} is not allowed; allowed: {allowed}"
        )
    size = p.stat().st_size
    if size == 0:
        raise ApiError(400, f"file is empty: {file_path!r}")
    if size > ATTACHMENT_MAX_BYTES:
        raise ApiError(
            400, f"file has {size} bytes; the platform takes at most {ATTACHMENT_MAX_BYTES}"
        )
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise ApiError(400, f"file not readable: {file_path!r} ({exc})") from exc
    return name, data, mime


@group.tool
async def list_attachments(application_id: str) -> dict:
    """List the file attachments of an application.

    Each entry holds `id`, `filename`, `mime` (the type that the server sniffed),
    `size`, `scanned` and `is_comparison_offer`. `scanned` stays false until the
    ClamAV scan reports clean; only then does `download_attachment` work. Upload with
    `upload_attachment`. A caller without the PII right does not see the files of the
    `isPII` form fields.
    """
    return await api().get(f"/applications/{application_id}/attachments")


@group.tool
async def upload_attachment(
    application_id: str,
    file_path: str,
    filename: str | None = None,
    field_key: str | None = None,
    is_comparison_offer: bool = False,
) -> dict:
    """Upload a local file as an attachment of an application.

    `POST /applications/{id}/attachments` (multipart field `file`). `file_path` is a
    path on the machine of the MCP server. `filename` overrides the name that the
    platform stores (the extension must still fit the content). `field_key` binds the
    file to a form field of type file; `is_comparison_offer` marks a comparison offer
    (Vergleichsangebot).

    Allowed: PDF, PNG, JPEG, GIF, WebP and the Office/OpenDocument types (doc, docx,
    xls, xlsx, ppt, pptx, odt, ods, odp), at most 10 MB. The server sniffs the content:
    a mismatch between content and extension gives 415, an oversize body 413, missing
    object storage 503. An upload is allowed in every state of the application, also a
    locked one.

    Requires `application.manage` (scope `applications:write`), or the caller is the
    logged-in creator of the application. Audited.

    Returns:
        The attachment: `id`, `filename`, `mime`, `size`, `scanned` (false: the virus
        scan still runs, the file cannot be downloaded yet) and `is_comparison_offer`.
    """
    name, data, mime = _attachment_part(file_path, filename)
    form: dict[str, str] = {"is_comparison_offer": "true" if is_comparison_offer else "false"}
    if field_key is not None:
        form["field_key"] = field_key
    return await api().post(
        f"/applications/{application_id}/attachments",
        files={"file": (name, data, mime)},
        data=form,
    )


@group.tool
async def download_attachment(
    attachment_id: str, target_path: str, overwrite: bool = False
) -> dict:
    """Download an attachment to a local file. The file content never enters the chat.

    `GET /attachments/{id}/download`, streamed to disk. `target_path` is a file path or
    an existing directory on the machine of the MCP server; for a directory the tool
    uses the stored file name. An existing file is kept unless `overwrite` is true.

    The same route serves the files of chat messages (the `attachments` of a ticket
    note, a to-do comment or an application comment); their read rule is the rule of
    reading the message, and `scanState` must be `clean`.

    409 while the virus scan runs (`scanned: false`, `scanState: scanning`), 410 after
    a finding removed the file, 404 for an unknown id or without read access to the
    application or the message.

    Returns:
        `path` (absolute), `filename`, `mime` and `size` in bytes.
    """
    target = Path(target_path).expanduser()
    if not target.is_dir():
        if not target.parent.is_dir():
            raise ApiError(400, f"directory not found: {str(target.parent)!r}")
        if target.exists() and not overwrite:
            raise ApiError(400, f"file exists (pass overwrite=true): {target_path!r}")
    async with api().stream("GET", f"/attachments/{attachment_id}/download") as resp:
        stored = _disposition_filename(resp.headers.get("content-disposition", ""))
        if not stored or "\x00" in stored:
            stored = f"attachment-{attachment_id}"
        final = target / stored if target.is_dir() else target
        if final.exists() and not overwrite:
            raise ApiError(400, f"file exists (pass overwrite=true): {str(final)!r}")
        fd, tmp = tempfile.mkstemp(dir=final.parent, prefix=".download-")
        size = 0
        try:
            with os.fdopen(fd, "wb") as out:
                async for chunk in resp.aiter_bytes(_DOWNLOAD_CHUNK):
                    out.write(chunk)
                    size += len(chunk)
            os.replace(tmp, final)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        mime = resp.headers.get("content-type", "application/octet-stream")
    return {
        "path": str(final.resolve()),
        "filename": stored,
        "mime": mime.split(";")[0].strip(),
        "size": size,
    }


@group.tool
async def delete_attachment(attachment_id: str) -> dict:
    """Delete a file attachment.

    Requires `application.manage` (scope `applications:write`); the logged-in creator
    may delete only while the state of the application allows edits (409 otherwise).
    """
    return await api().delete(f"/attachments/{attachment_id}")


def register(mcp: FastMCP) -> None:
    """Register the votes/meetings/protocol/delegations tool group."""
    group.register(mcp)
