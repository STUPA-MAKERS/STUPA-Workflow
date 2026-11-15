"""Known names of a Sitzung for the blackout in the protocol editor (specs 000969, 000970).

The editor puts the blackout marker around a known name right after a keeper types
it. A known name is a pair of a first name and a last name. The pairs come from
three sources:

1. the display name of each account that is not merged into another account,
2. the name of the applicant of each Antrag on the agenda of the Sitzung,
3. the name of each guest of the Sitzung.

Of each name, the first word is the first name and the last word is the last name.
A name of one word gives no pair. A name with an `@` is an e-mail address, not a
name, and gives no pair. An anonymized applicant or guest has no name and gives no
pair. The answer holds only the pairs: no id, no e-mail address and no source.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Applicant
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.meetings.models import MeetingAgendaItem, MeetingGuest


def name_pair(name: str | None) -> tuple[str, str] | None:
    """Return the first and the last word of a name, or None if it is no full name."""
    if not name or "@" in name:
        return None
    words = name.split()
    if len(words) < 2:
        return None
    return words[0], words[-1]


def name_pairs(names: Iterable[str | None]) -> list[tuple[str, str]]:
    """Return the pairs of the names once each, compared without case, sorted."""
    pairs: dict[tuple[str, str], tuple[str, str]] = {}
    for name in names:
        pair = name_pair(name)
        if pair is not None:
            pairs.setdefault((pair[0].casefold(), pair[1].casefold()), pair)
    return [pairs[key] for key in sorted(pairs)]


async def known_names(session: AsyncSession, meeting_id: UUID) -> list[tuple[str, str]]:
    """Return the known names of the Sitzung as pairs of first and last name."""
    accounts = (
        await session.scalars(
            select(PrincipalRow.display_name).where(PrincipalRow.merged_into.is_(None))
        )
    ).all()
    applicants = (
        await session.scalars(
            select(Applicant.name)
            .join(MeetingAgendaItem, MeetingAgendaItem.application_id == Applicant.application_id)
            .where(MeetingAgendaItem.meeting_id == meeting_id)
        )
    ).all()
    guests = (
        await session.scalars(
            select(MeetingGuest.display_name).where(MeetingGuest.meeting_id == meeting_id)
        )
    ).all()
    return name_pairs([*accounts, *applicants, *guests])
