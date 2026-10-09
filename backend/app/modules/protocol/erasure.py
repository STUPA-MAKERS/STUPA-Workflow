"""Erasure of a candidate name from the protocol text (F2, DSGVO Art. 17).

``embed_votes`` copies the callout of an election into ``protocol.markdown``, and the
protokollant can insert the same callout into the body of an agenda item. Both copies
name every candidate with the votes. After ``voting.erasure.erase_candidacies`` changed
the candidate list of an election, this module writes the same change into these
copies.

The module builds the internal callout of the election twice from the stored result:
with the config before and after the change. The lines that differ carry the old name;
only these lines change, and only inside the callout of that election (the head line
with the question and the round finds it). A line that the protokollant edited does
not match and stays as it is. The public callout names the elected candidates only,
so it never carries the name of a candidate who was not elected.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.livevote.models import MeetingAgendaItem
from app.modules.protocol.markdown import build_election_snippet
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import election_snippet_of
from app.modules.voting.erasure import ErasedCandidacy
from app.modules.voting.models import Vote
from app.modules.voting.schemas import ElectionResultOut
from app.shared.config_schemas import ElectionConfig

# The head line of a callout and the changed lines in it (old line -> new line).
_Change = tuple[str, dict[str, str]]


def _callout(vote: Vote, config: dict) -> list[str]:
    """Build the lines of the internal callout of ``vote`` with ``config``."""
    stored = vote.election_result
    result = ElectionResultOut.model_validate(stored) if stored else None
    view = election_snippet_of(
        ElectionConfig.model_validate(config),
        result,
        question=vote.question,
        round_=vote.round or 1,
    )
    return build_election_snippet(view).split("\n")


def _change_of(erased: ErasedCandidacy) -> _Change:
    """Return the head line and the changed lines of one erased candidacy."""
    old = _callout(erased.vote, erased.old_config)
    new = _callout(erased.vote, erased.vote.config)
    return old[0], {o: n for o, n in zip(old, new, strict=True) if o != n}


def rewrite_callouts(text: str, changes: Sequence[_Change]) -> str:
    """Write the changed lines into each callout of ``text`` whose head matches.

    The callout runs from its head line over the following ``>`` lines. The indent of
    a line stays. A text without a matching head comes back unchanged.
    """
    lines = text.split("\n")
    for head, swaps in changes:
        i = 0
        while i < len(lines):
            if lines[i].strip() != head:
                i += 1
                continue
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                line = lines[i]
                new = swaps.get(line.strip())
                if new is not None:
                    lines[i] = line[: len(line) - len(line.lstrip())] + new
                i += 1
    return "\n".join(lines)


async def erase_candidate_names(session: AsyncSession, erased: Sequence[ErasedCandidacy]) -> None:
    """Write the erased candidate names into the protocol copies (no commit).

    The method changes ``protocol.markdown`` and the agenda item bodies of the
    meetings of the changed elections. An election without a meeting has no
    protocol. A stored PDF does not change.
    """
    by_meeting: dict[UUID, list[_Change]] = {}
    for item in erased:
        if item.vote.meeting_id is None:
            continue
        change = _change_of(item)
        if change[1]:
            by_meeting.setdefault(item.vote.meeting_id, []).append(change)
    if not by_meeting:
        return
    meeting_ids = list(by_meeting)
    protocols = (
        await session.scalars(select(Protocol).where(Protocol.meeting_id.in_(meeting_ids)))
    ).all()
    for protocol in protocols:
        markdown = rewrite_callouts(protocol.markdown or "", by_meeting[protocol.meeting_id])
        if markdown != (protocol.markdown or ""):
            protocol.markdown = markdown
    items = (
        await session.scalars(
            select(MeetingAgendaItem).where(
                MeetingAgendaItem.meeting_id.in_(meeting_ids),
                MeetingAgendaItem.body.is_not(None),
            )
        )
    ).all()
    for agenda_item in items:
        body = agenda_item.body or ""
        rewritten = rewrite_callouts(body, by_meeting[agenda_item.meeting_id])
        if rewritten != body:
            agenda_item.body = rewritten
