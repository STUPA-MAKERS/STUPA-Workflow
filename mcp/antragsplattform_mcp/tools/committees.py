"""Gremium pages, the Kalender and the votes of a Gremium without a meeting.

The Gremium pages read what the Gremien page of the app shows: the overview, the
members, the meetings, the decisions, the attendance and the Info tab. The Kalender
tools read the entries and manage the Termine with their invitations. A vote without a
meeting is a poll (Umfrage) or an Umlaufverfahren; no tool casts a ballot or objects.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params
from .meetings import download_to

group = ToolGroup()


@group.tool
async def list_gremien_master() -> list:
    """List every Gremium as master data (id, name, variant) for a picker."""
    return await api().get("/committees")


@group.tool
async def list_cd_variant_options() -> list:
    """List the CD variants (id, key, name) for the variant of a Gremium."""
    return await api().get("/cd-variants")


@group.tool
async def gremien_overview() -> list:
    """List the Gremien that the caller sees, with `isMember` and `roleName`."""
    return await api().get("/committees/overview")


@group.tool
async def gremium_members(gremium_id: str, former: bool = False) -> list:
    """List the members of a Gremium by role, or the former members with `former=True`."""
    return await api().get(
        f"/committees/{gremium_id}/members", params=params(former=former or None)
    )


@group.tool
async def gremium_meetings(gremium_id: str) -> list:
    """List the meetings of a Gremium, the newest first, with attendance and protocol state."""
    return await api().get(f"/committees/{gremium_id}/meetings")


@group.tool
async def gremium_decisions(
    gremium_id: str,
    cursor: str | None = None,
    q: str | None = None,
    result: Literal["passed", "rejected"] | None = None,
    kind: Literal["application", "election", "motion"] | None = None,
    since: str | None = None,
) -> dict:
    """List the closed votes (Beschlüsse) of a Gremium, the newest first, 30 per page.

    Args:
        cursor: `nextCursor` of the previous page.
        q: Search in the question or the meeting title.
        since: ISO date; only votes from this day on.
    """
    return await api().get(
        f"/committees/{gremium_id}/decisions",
        params=params(cursor=cursor, q=q, result=result, kind=kind, since=since),
    )


@group.tool
async def gremium_attendance(
    gremium_id: str,
    from_month: str | None = None,
    to_month: str | None = None,
    term: str | None = None,
) -> dict:
    """Give the attendance per member and month (at most 24 months).

    Without a range the last six months. `term` is a day of the term whose unexcused
    absences the rows count.

    Args:
        from_month: YYYY-MM.
        to_month: YYYY-MM.
        term: ISO date of a day in the term.
    """
    return await api().get(
        f"/committees/{gremium_id}/attendance",
        params=params(**{"from": from_month, "to": to_month, "term": term}),
    )


@group.tool
async def gremium_member_attendance(
    gremium_id: str, principal_id: str, month: str, pool: bool = False
) -> dict:
    """Give the closed meetings of one month (YYYY-MM) with the state of one member.

    With `pool` the person is read as a pool substitute: the state is `seat` (with the
    represented member) or `no_seat`.
    """
    return await api().get(
        f"/committees/{gremium_id}/attendance/{principal_id}",
        params={"month": month, **({"pool": "true"} if pool else {})},
    )


@group.tool
async def export_gremium_attendance_xlsx(
    gremium_id: str, first_day: str, last_day: str, target_path: str, overwrite: bool = False
) -> dict:
    """Export the attendance of a date range as `.xlsx` to a local file.

    Requires `session.manage` in the Gremium. The days are ISO dates, both included.
    """
    return await download_to(
        "GET",
        f"/committees/{gremium_id}/attendance/export.xlsx",
        target_path,
        overwrite=overwrite,
        fallback="anwesenheit.xlsx",
        query={"from": first_day, "to": last_day},
    )


@group.tool
async def get_gremium_info(gremium_id: str) -> dict:
    """Read the Info tab of a Gremium: the Markdown text, the links, `version`, `canEdit`."""
    return await api().get(f"/committees/{gremium_id}/info")


@group.tool
async def set_gremium_info(
    gremium_id: str, body_md: str, links: list[S.GremiumInfoLink], version: int
) -> dict:
    """Save the text and the links of the Info tab of a Gremium together.

    Requires `info.write` in the Gremium. `version` is the version read with
    `get_gremium_info`; another version gives 409 `gremium_info_version_conflict`.
    """
    return await api().put(
        f"/committees/{gremium_id}/info",
        json={
            "bodyMd": body_md,
            "links": [link.model_dump() for link in links],
            "version": version,
        },
    )


@group.tool
async def notify_gremium_members(gremium_id: str, subject: str, message: str) -> dict:
    """Mail a message to every member and pool substitute of a Gremium, the sender included.

    Requires `members.notify` in the Gremium. The subject holds 1 to 200 characters, the
    message 1 to 10000 characters of plain text. The Reply-To of the mail is the caller.
    The answer is `{"recipients": n}`.
    """
    return await api().post(
        f"/committees/{gremium_id}/notify", json={"subject": subject, "message": message}
    )


@group.tool
async def gremium_meeting_defaults(gremium_id: str) -> dict:
    """What a new meeting of the Gremium allows (guests vote, quorum); session.manage."""
    return await api().get(f"/committees/{gremium_id}/meeting-defaults")


@group.tool
async def gremium_meeting_members(gremium_id: str) -> list:
    """List the members of a Gremium as protokollant candidates (`canKeepProtocol`)."""
    return await api().get(f"/committees/{gremium_id}/meeting-members")


@group.tool
async def download_gremium_logo(gremium_id: str, target_path: str, overwrite: bool = False) -> dict:
    """Download the square logo of the CD variant of a Gremium to a local file."""
    return await download_to(
        "GET",
        f"/committees/{gremium_id}/logo",
        target_path,
        overwrite=overwrite,
        fallback=f"logo-{gremium_id}",
    )


@group.tool
async def gremium_public_preview(gremium_id: str) -> dict:
    """Count the protocols that the switch `protocolsPublic` would publish (admin.gremien)."""
    return await api().get(f"/admin/committees/{gremium_id}/public-preview")


@group.tool
async def calendar_entries(first_day: str, last_day: str, mine: bool = False) -> list:
    """Read the Kalender entries between two ISO dates, both included.

    The entries are meetings, due cards, Events, Termine and external entries. `mine`
    keeps the assigned cards and the Termine that the caller created or is invited to.
    """
    return await api().get(
        "/calendar/entries",
        params=params(**{"from": first_day, "to": last_day, "mine": mine or None}),
    )


@group.tool
async def calendar_search(q: str) -> list:
    """Search the Kalender entries of every month by title, the nearest to today first."""
    return await api().get("/calendar/search", params={"q": q})


@group.tool
async def calendar_people(q: str) -> list:
    """Search the active accounts by name, for the invitation of a person to a Termin."""
    return await api().get("/calendar/people", params={"q": q})


@group.tool
async def get_appointment(appointment_id: str) -> dict:
    """Read one Termin with its invitations and answers."""
    return await api().get(f"/calendar/appointments/{appointment_id}")


@group.tool
async def create_appointment(appointment: S.AppointmentIn) -> dict:
    """Create a Termin of the caller and invite its teams and persons.

    The caller invites only own teams, or every team with `calendar.manage`.

    The invited persons get a mail with an `.ics` file.
    """
    return await api().post("/calendar/appointments", json=dump_create(appointment))


@group.tool
async def update_appointment(appointment_id: str, appointment: S.AppointmentIn) -> dict:
    """Replace the data and the invitations of a Termin (creator or `calendar.manage`)."""
    return await api().put(
        f"/calendar/appointments/{appointment_id}", json=dump_create(appointment)
    )


@group.tool
async def delete_appointment(appointment_id: str) -> dict:
    """Delete a Termin (creator or `calendar.manage`). Ask the user first."""
    await api().delete(f"/calendar/appointments/{appointment_id}")
    return {"deleted": True}


@group.tool
async def answer_appointment(
    appointment_id: str, answer: Literal["accept", "tentative", "decline"]
) -> dict:
    """Store the own answer to a Termin, until the Termin ends."""
    return await api().put(
        f"/calendar/appointments/{appointment_id}/answer", json={"answer": answer}
    )


@group.tool
async def get_external_calendar_entry(entry_id: str) -> dict:
    """Read one entry of an external calendar that the caller reads."""
    return await api().get(f"/calendar/external/{entry_id}")


@group.tool
async def list_external_calendars() -> list:
    """List the subscribed external calendars with their newest fetch (admin)."""
    return await api().get("/admin/calendars")


@group.tool
async def create_external_calendar(calendar: S.ExternalCalendarIn) -> dict:
    """Subscribe an external ICS calendar; the worker fetches it within a minute."""
    return await api().post("/admin/calendars", json=dump_create(calendar))


@group.tool
async def update_external_calendar(calendar_id: str, calendar: S.ExternalCalendarIn) -> dict:
    """Change an external calendar; a new address starts a fetch."""
    return await api().put(f"/admin/calendars/{calendar_id}", json=dump_create(calendar))


@group.tool
async def delete_external_calendar(calendar_id: str) -> dict:
    """Delete an external calendar together with its entries. Ask the user first."""
    await api().delete(f"/admin/calendars/{calendar_id}")
    return {"deleted": True}


@group.tool
async def fetch_external_calendar(calendar_id: str) -> dict:
    """Make an external calendar due at once ("Jetzt abrufen")."""
    return await api().post(f"/admin/calendars/{calendar_id}/fetch")


@group.tool
async def list_votes(
    status: list[Literal["draft", "open", "closed", "cancelled"]] | None = None,
    gremium_id: str | None = None,
    q: str | None = None,
    kind: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List the votes that the caller can read, the open votes first.

    Without `status` the list leaves out the drafts.

    Args:
        kind: `motion`, `election`, `poll` or `circular`.
    """
    return await api().get(
        "/votes",
        params=params(
            status=status, gremiumId=gremium_id, q=q, kind=kind, limit=limit, offset=offset
        ),
    )


@group.tool
async def get_circular_vote_rules() -> dict:
    """Return `minDays`: the least number of days of the window of an Umlaufverfahren."""
    return await api().get("/votes/circular-rules")


@group.tool
async def create_gremium_vote(vote: S.GremiumVoteCreate) -> dict:
    """Create a poll (Umfrage) or an Umlaufverfahren of a Gremium, without a meeting.

    `kind: "circular"` is an Umlaufverfahren: Ja / Nein / Enthaltung with the majority of
    the members; leave `mode`, `options` and `maxChoices` out. `kind: "poll"` needs
    `mode` and `options`. Requires `vote.manage` in the Gremium. No tool casts a ballot
    or an objection: only a person does that.
    """
    return await api().post("/votes", json=dump_create(vote))


@group.tool
async def update_poll(vote_id: str, patch: S.PollPatch) -> dict:
    """Change the question, the options or the end of a poll without ballots.

    409 `poll_has_answers` once a ballot exists, `poll_not_editable` after the end.
    """
    return await api().patch(f"/votes/{vote_id}", json=dump_patch(patch))


@group.tool
async def delete_vote(vote_id: str) -> dict:
    """Delete a vote without a meeting that is a draft or cancelled (409 otherwise)."""
    await api().delete(f"/votes/{vote_id}")
    return {"deleted": True}


def register(mcp: FastMCP) -> None:
    """Register the Gremium, Kalender and vote tool group."""
    group.register(mcp)


@group.tool
async def list_teams() -> list:
    """List every team by name with `isMember`, `canManage` and its own `boardId`.

    A team with `gremiumId` is the team of that Gremium: its members are the members and
    the substitute pool of the Gremium. `parentId` marks a sub-team.
    """
    return await api().get("/teams")


@group.tool
async def get_team(team_id: str) -> dict:
    """Read a team with its sub-teams, and its members for a member or a manager."""
    return await api().get(f"/teams/{team_id}")


@group.tool
async def create_team(team: S.TeamCreate) -> dict:
    """Create a team with its board; the caller becomes its manager.

    A team at the top needs `team.create`; a sub-team needs a manager of the parent.
    """
    return await api().post("/teams", json=dump_create(team))


@group.tool
async def update_team(team_id: str, team: S.TeamPatch) -> dict:
    """Rename a team or move it under another parent (a manager of the team).

    The team of a Gremium follows its Gremium: 409 `inherent_team`.
    """
    return await api().patch(f"/teams/{team_id}", json=dump_patch(team))


@group.tool
async def delete_team(team_id: str) -> dict:
    """Delete a team without sub-teams and without cards on its board. Ask the user first."""
    await api().delete(f"/teams/{team_id}")
    return {"deleted": True}


@group.tool
async def set_team_member(
    team_id: str, principal_id: str, role: Literal["member", "manager"] = "member"
) -> dict:
    """Add a person to a team or change the role (a manager; not the team of a Gremium)."""
    return await api().put(f"/teams/{team_id}/members/{principal_id}", json={"role": role})


@group.tool
async def remove_team_member(team_id: str, principal_id: str) -> dict:
    """Remove a person from a team; the last manager stays (409 `last_manager`)."""
    return await api().delete(f"/teams/{team_id}/members/{principal_id}")


@group.tool
async def get_team_info(team_id: str) -> dict:
    """Read the Info tab of a free team: the Markdown text, the links, `version`, `canEdit`.

    A member or a manager reads it; the team of a Gremium gives 404 (use `get_gremium_info`).
    """
    return await api().get(f"/teams/{team_id}/info")


@group.tool
async def set_team_info(
    team_id: str, body_md: str, links: list[S.GremiumInfoLink], version: int
) -> dict:
    """Save the text and the links of the Info tab of a free team together.

    Requires a manager of the team. `version` is the version read with `get_team_info`;
    another version gives 409 `team_info_version_conflict`.
    """
    return await api().put(
        f"/teams/{team_id}/info",
        json={
            "bodyMd": body_md,
            "links": [link.model_dump() for link in links],
            "version": version,
        },
    )
