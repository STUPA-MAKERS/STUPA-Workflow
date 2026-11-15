"""The public decisions of the gremien that publish their protocols (spec 000926).

A decision of a meeting is public only as a part of a public protocol. The list reads
the stored public version (`protocol.public_content`) of each visible protocol, so it
holds only closed votes that are no poll, of a TOP that is not internal, of a protocol
that is public (`visible_clause`). It never holds a name: a motion gives its question,
its date, the title of its meeting, its result and the sums of the votes; an election
gives its question and its date only, so the elected persons stay out. A TOP with more
than one vote on the same question gives only the last one (spec 000945).

A circular vote stands in no protocol. The list reads each closed circular vote of a
Gremium with `protocols_public` from its row, from the close of the vote on
(§F/meetings/voting/000949). A vote that an objection cancelled is not closed, so it
stays out.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date as _date
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field

from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.modules.protocol.public import (
    PublicDecision,
    PublicFilter,
    PublicGremiumRef,
    PublicProtocolService,
    PublicSnapshot,
    VoteResult,
    meeting_day,
    semester_of,
)
from app.modules.voting.schemas import VoteOut
from app.settings import get_settings
from app.shared.schemas import FrozenCamelModel


class PublicDecisionOut(FrozenCamelModel, frozen=True):
    """One public decision. An election has no meeting title, result or sums.

    A circular vote has no protocol and no meeting title, and its date is the day of
    its close.
    """

    protocol_id: UUID | None = Field(default=None, alias="protocolId")
    gremium: PublicGremiumRef
    date: _date
    semester: str
    kind: Literal["motion", "election", "circular"] = "motion"
    question: str | None = None
    meeting_title: str | None = Field(default=None, alias="meetingTitle")
    result: VoteResult | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class PublicDecisionPage(FrozenCamelModel, frozen=True):
    """One page of the public decisions."""

    items: list[PublicDecisionOut]
    total: int
    limit: int
    offset: int


def _decision_out(
    decision: PublicDecision, protocol: Protocol, meeting: Meeting, gremium: Gremium
) -> PublicDecisionOut:
    day = meeting_day(meeting)
    election = decision.kind == "election"
    return PublicDecisionOut(
        protocolId=protocol.id,
        gremium=PublicGremiumRef(id=gremium.id, name=gremium.name, slug=gremium.slug),
        date=day,
        semester=semester_of(day),
        kind=decision.kind,
        question=decision.question,
        meetingTitle=None if election else meeting.title,
        result=None if election else decision.result,
        counts={} if election else dict(decision.counts),
    )


def _matches(decision: PublicDecision, needle: str | None) -> bool:
    return needle is None or needle in (decision.question or "").casefold()


def last_results(decisions: Sequence[PublicDecision]) -> list[PublicDecision]:
    """Keep of the votes of one TOP with the same question only the last one.

    A repeated vote and the rounds of an election have the same question
    (§F/public/public-pages/000945). The decisions stand in the order of their close, so
    the last one of a question is its result. A vote without a question always stays.
    """
    last = {
        (decision.kind, decision.question): index
        for index, decision in enumerate(decisions)
        if decision.question
    }
    return [
        decision
        for index, decision in enumerate(decisions)
        if not decision.question or last[(decision.kind, decision.question)] == index
    ]


def decisions_of(
    protocol: Protocol, meeting: Meeting, gremium: Gremium, *, q: str | None = None
) -> list[PublicDecisionOut]:
    """Return the public decisions of one visible protocol, in the agenda order.

    `q` keeps the decisions whose question holds the text. The search of the protocol
    rows also finds a protocol by its title or its TOP text, so the list filters again.
    """
    needle = q.casefold() if q else None
    snapshot = PublicSnapshot.model_validate(protocol.public_content or {})
    of_tops = [
        decision
        for top in snapshot.tops
        if not top.non_public
        for decision in last_results(top.decisions)
    ]
    return [
        _decision_out(decision, protocol, meeting, gremium)
        for decision in of_tops
        if _matches(decision, needle)
    ]


def _in_filter(day: _date, question: str | None, flt: PublicFilter) -> bool:
    """Tell if a circular decision of `day` passes the semester, year and text filters."""
    return (
        (flt.semester is None or semester_of(day) == flt.semester)
        and (flt.year is None or day.year == flt.year)
        and (not flt.q or flt.q.strip().casefold() in (question or "").casefold())
    )


def circular_out(view: VoteOut, gremium: Gremium, tz: ZoneInfo) -> PublicDecisionOut | None:
    """Build the public form of one closed circular vote: no name, no meeting.

    Returns:
        The decision, or `None` for a vote without the time of its close.
    """
    if view.closed_at is None:
        return None
    day = view.closed_at.astimezone(tz).date()
    return PublicDecisionOut(
        gremium=PublicGremiumRef(id=gremium.id, name=gremium.name, slug=gremium.slug),
        date=day,
        semester=semester_of(day),
        kind="circular",
        question=view.question,
        result=view.result,
        counts=dict(view.tally.counts),
    )


def circular_decisions(
    views: Sequence[tuple[VoteOut, Gremium]], flt: PublicFilter, tz: ZoneInfo
) -> list[PublicDecisionOut]:
    """Build the circular decisions that pass the semester, year and text filters."""
    outs = [circular_out(view, gremium, tz) for view, gremium in views]
    return [out for out in outs if out is not None and _in_filter(out.date, out.question, flt)]


async def list_public_decisions(
    service: PublicProtocolService, flt: PublicFilter, *, limit: int, offset: int
) -> PublicDecisionPage:
    """List the public decisions, newest day first.

    The page is cut after the read of the visible protocols, because a decision of a
    meeting is a part of the stored public version and has no row of its own. The
    circular decisions join the list by their day; the sort is stable, so the decisions
    of one protocol keep the agenda order.
    """
    rows = await service.visible_rows(flt)
    of_meetings = [
        out
        for protocol, meeting, gremium in rows
        for out in decisions_of(protocol, meeting, gremium, q=flt.q)
    ]
    circular = circular_decisions(
        await service.circular_votes(flt), flt, ZoneInfo(get_settings().local_timezone)
    )
    found = sorted([*of_meetings, *circular], key=lambda out: out.date, reverse=True)
    return PublicDecisionPage(
        items=found[offset : offset + limit], total=len(found), limit=limit, offset=offset
    )
