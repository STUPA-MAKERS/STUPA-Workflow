"""The public decisions of the gremien that publish their protocols (spec 000926).

A decision is public only as a part of a public protocol. The list reads the stored
public version (`protocol.public_content`) of each visible protocol, so it holds only
closed votes that are no poll, of a TOP that is not internal, of a protocol that is
public (`visible_clause`). It never holds a name: a motion gives its question, its
date, the title of its meeting, its result and the sums of the votes; an election
gives its question and its date only, so the elected persons stay out.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Literal
from uuid import UUID

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
from app.shared.schemas import FrozenCamelModel


class PublicDecisionOut(FrozenCamelModel, frozen=True):
    """One public decision. An election has no meeting title, result or sums."""

    protocol_id: UUID = Field(alias="protocolId")
    gremium: PublicGremiumRef
    date: _date
    semester: str
    kind: Literal["motion", "election"] = "motion"
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


def decisions_of(
    protocol: Protocol, meeting: Meeting, gremium: Gremium, *, q: str | None = None
) -> list[PublicDecisionOut]:
    """Return the public decisions of one visible protocol, in the agenda order.

    `q` keeps the decisions whose question holds the text. The search of the protocol
    rows also finds a protocol by its title or its TOP text, so the list filters again.
    """
    needle = q.casefold() if q else None
    snapshot = PublicSnapshot.model_validate(protocol.public_content or {})
    return [
        _decision_out(decision, protocol, meeting, gremium)
        for top in snapshot.tops
        if not top.non_public
        for decision in top.decisions
        if _matches(decision, needle)
    ]


async def list_public_decisions(
    service: PublicProtocolService, flt: PublicFilter, *, limit: int, offset: int
) -> PublicDecisionPage:
    """List the public decisions, newest meeting first.

    The page is cut after the read of the visible protocols, because a decision is a
    part of the stored public version and has no row of its own.
    """
    rows = await service.visible_rows(flt)
    found = [
        out
        for protocol, meeting, gremium in rows
        for out in decisions_of(protocol, meeting, gremium, q=flt.q)
    ]
    return PublicDecisionPage(
        items=found[offset : offset + limit], total=len(found), limit=limit, offset=offset
    )
