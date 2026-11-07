"""Erasure of a candidate name from the protocol text (DSGVO Art. 17).

``embed_votes`` copies the callout of an election into ``protocol.markdown``, and the
protokollant can insert the same callout into the body of an agenda item. Both copies
name every candidate with the votes. After ``voting.erasure.erase_candidacies`` changed
the candidate list of an election, this module writes the same change into these
copies.

The module builds the internal callout of the election twice from the stored result:
with the config before and after the change. Only a callout in the text that equals the
old callout line for line (head, meta, votes, result, notes) changes into the new one.
The head line alone does not identify an election: two elections of one meeting can
share the question (or both lack one), and the person can lose the one and win the
other. A callout that the protokollant edited does not match and stays as it is. The
public callout names the elected candidates only, so it never carries the name of a
candidate who was not elected.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import partial, reduce
from typing import Any
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

#: The lines of the old callout and of the new callout of one election (same length).
_Change = tuple[Sequence[str], Sequence[str]]

#: The marker that opens a callout (``> [!abstimmung]``, ``> [!note]``, ...).
_OPENER = re.compile(r"^>\s*\[!")


def _callout(vote: Vote, config: dict[str, Any]) -> list[str]:
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
    """Return the old and the new callout lines of one erased candidacy."""
    old = [line.strip() for line in _callout(erased.vote, erased.old_config)]
    return old, [line.strip() for line in _callout(erased.vote, erased.vote.config)]


def _block_end(lines: Sequence[str], start: int) -> int:
    """Return the index after the callout that opens at ``start``.

    The callout runs over the following ``>`` lines and ends before a line that is no
    quote or that opens the next callout.
    """
    ends = (
        end
        for end in range(start + 1, len(lines))
        if not lines[end].strip().startswith(">") or _OPENER.match(lines[end].strip())
    )
    return next(ends, len(lines))


def _indented(current: str, line: str) -> str:
    """Return ``line`` with the indent of ``current``."""
    return current[: len(current) - len(current.lstrip())] + line


def _rewrite_one(
    changes: Sequence[_Change], lines: tuple[str, ...], start: int
) -> tuple[str, ...]:
    """Replace the callout that opens at ``start`` when it equals an old callout."""
    end = _block_end(lines, start)
    block = [line.strip() for line in lines[start:end]]
    new = next((new for old, new in changes if block == list(old)), None)
    return (
        lines
        if new is None
        else (
            *lines[:start],
            *(_indented(lines[start + j], line) for j, line in enumerate(new)),
            *lines[start + len(new) :],
        )
    )


def rewrite_callouts(text: str, changes: Sequence[_Change]) -> str:
    """Replace each callout of ``text`` that equals an old callout with its new form.

    A callout matches only when all its lines (without the indent) equal the old
    callout. The indent of a line stays. A text without a matching callout comes back
    unchanged. A callout never holds the opener of another one, so every opener line
    starts a callout of its own.
    """
    lines = tuple(text.split("\n"))
    openers = (i for i, line in enumerate(lines) if _OPENER.match(line.strip()))
    return "\n".join(reduce(partial(_rewrite_one, changes), openers, lines))


async def erase_candidate_names(session: AsyncSession, erased: Sequence[ErasedCandidacy]) -> None:
    """Write the erased candidate names into the protocol copies (no commit).

    The method changes ``protocol.markdown`` and the agenda item bodies of the
    meetings of the changed elections. An election without a meeting has no
    protocol. A stored PDF does not change.
    """
    changes = [
        (item.vote.meeting_id, _change_of(item))
        for item in erased
        if item.vote.meeting_id is not None
    ]
    changed = [(meeting_id, change) for meeting_id, change in changes if change[0] != change[1]]
    by_meeting: dict[UUID, list[_Change]] = {
        meeting_id: [change for other, change in changed if other == meeting_id]
        for meeting_id, _ in changed
    }
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
