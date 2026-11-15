"""The Umlaufverfahren of a Gremium in the protocol of its next meeting.

The Geschäftsordnung asks the protocol of the next Sitzung to hold each Beschluss of
an Umlaufverfahren and its result (spec 000916). The block lists the circular votes of
the Gremium that closed after the start of the meeting before and, for a started
meeting, not after its own start. It stands in front of the first TOP and has no
heading, because the render service numbers each heading as a TOP.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meetings.models import Meeting
from app.modules.protocol.markdown import build_vote_snippet
from app.modules.protocol.public import PublicDecision
from app.modules.voting.circular import CIRCULAR
from app.modules.voting.models import Vote
from app.modules.voting.schemas import VoteOut
from app.modules.voting.service import VotingService

#: The line in front of the circular votes.
CIRCULAR_LEAD = "**Beschlüsse im Umlaufverfahren seit der letzten Sitzung**"


def circular_note(result: str | None, closed_at: datetime | None, tz: ZoneInfo) -> str:
    """Return the note line of a circular vote: the kind, the end and the result."""
    ended = f"beendet am {closed_at.astimezone(tz).strftime('%d.%m.%Y')}" if closed_at else None
    outcome = "angenommen" if result == "passed" else "abgelehnt"
    return " · ".join(part for part in ("Umlaufverfahren", ended, outcome) if part)


def circular_snippet(view: VoteOut, tz: ZoneInfo) -> str:
    """Build the callout of one closed circular vote: question, counts and result."""
    question = view.question or "Umlaufverfahren"
    return build_vote_snippet(
        question,
        view.tally.counts,
        note=circular_note(view.result, getattr(view, "closed_at", None), tz),
    )


def build_circular_block(snippets: Sequence[str]) -> str:
    """Join the lead line and the callouts; no vote gives no block."""
    return "\n\n".join([CIRCULAR_LEAD, *snippets]) if snippets else ""


async def _previous_start(
    session: AsyncSession, meeting_id: UUID, gremium_id: UUID, started: datetime | None
) -> datetime | None:
    """Return the start of the meeting of the Gremium before this one, if any."""
    query = (
        select(Meeting.started_at)
        .where(
            Meeting.gremium_id == gremium_id,
            Meeting.id != meeting_id,
            Meeting.started_at.is_not(None),
            *([Meeting.started_at < started] if started is not None else []),
        )
        .order_by(Meeting.started_at.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()


async def circular_views(
    session: AsyncSession, meeting: Meeting | None, voting: VotingService
) -> list[VoteOut]:
    """Read the closed circular votes that the protocol of ``meeting`` lists.

    A protocol without a meeting row, or a meeting without a Gremium, lists none.
    """
    gremium_id: UUID | None = getattr(meeting, "gremium_id", None)
    if meeting is None or gremium_id is None:
        return []
    until: datetime | None = getattr(meeting, "started_at", None)
    after = await _previous_start(session, meeting.id, gremium_id, until)
    ids = (
        (
            await session.execute(
                select(Vote.id)
                .where(
                    Vote.kind == CIRCULAR,
                    Vote.status == "closed",
                    Vote.eligible_group == str(gremium_id),
                    *([Vote.closed_at > after] if after is not None else []),
                    *([Vote.closed_at <= until] if until is not None else []),
                )
                .order_by(Vote.closed_at)
            )
        )
        .scalars()
        .all()
    )
    return [await voting.get(vote_id) for vote_id in ids]


def circular_decision(view: VoteOut, tz: ZoneInfo) -> PublicDecision:
    """Build the public form of one circular vote: question, day, result and sums.

    The public form holds no name (§F/meetings/protocols/000934).
    """
    closed_at: datetime | None = getattr(view, "closed_at", None)
    return PublicDecision(
        kind="circular",
        question=view.question,
        counts=dict(view.tally.counts),
        result=view.result,
        majorityRule=getattr(view, "majority_rule", "members_majority"),
        secret=bool(getattr(view, "secret", True)),
        closedOn=closed_at.astimezone(tz).date() if closed_at else None,
    )


async def circular_block(
    session: AsyncSession, meeting: Meeting | None, voting: VotingService, tz: ZoneInfo
) -> str:
    """Build the block of the circular votes that the protocol of ``meeting`` lists."""
    views = await circular_views(session, meeting, voting)
    return build_circular_block([circular_snippet(view, tz) for view in views])
