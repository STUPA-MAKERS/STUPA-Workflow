"""Erasure of a person from the candidate lists of the elections (F2, DSGVO Art. 17).

An election (``vote.kind = 'election'``) keeps the name of each candidate in
``vote.config.candidates``; the ballots and ``election_result`` name the candidates by
their id only. The erasure of a principal replaces the name of each candidacy of that
principal with ``ERASED_CANDIDATE_NAME``, unless the principal was elected: the result
of an election is a documented resolution, so an elected candidate keeps the name.

A candidacy counts as elected when the closed result of a vote of the same election
lists the candidate. An election is the first round and its runoffs: a runoff copies
the candidates with their ``principalId``, so each round carries the candidacy and a
win in a runoff also keeps the name in the earlier rounds. An election that is not
decided (open, a lot that is pending, a runoff that is pending) elected nobody yet, so
its candidacy gets the placeholder.

The function finds a candidacy by its ``principalId`` only. A candidate without an
account link has a name only, and the function never matches a name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.voting.election import ELECTION
from app.modules.voting.models import Vote

# The name that replaces the name of an erased candidate who was not elected.
ERASED_CANDIDATE_NAME = "Gelöscht"


@dataclass(frozen=True, slots=True)
class ErasedCandidacy:
    """One election whose candidate list changed: the vote and its config before."""

    vote: Vote
    old_config: dict[str, Any]


def _candidacy(vote: Vote, principal: str) -> dict[str, Any] | None:
    """Return the stored candidate of ``principal`` in ``vote``, or None."""
    for candidate in vote.config.get("candidates") or []:
        if candidate.get("principalId") == principal:
            return candidate
    return None


def _elected_in(vote: Vote, candidate_id: str) -> bool:
    """Tell whether the closed result of ``vote`` elected ``candidate_id``."""
    stored = vote.election_result
    if vote.status != "closed" or not stored:
        return False
    return candidate_id in (stored.get("elected") or [])


def _root_of(vote: Vote, by_id: dict[UUID, Vote]) -> UUID:
    """Return the first round of the election of ``vote`` among the found rounds.

    Each runoff carries the candidacy of its parent, so the walk stays inside the
    found rows. A parent that is gone (``parent_vote_id`` is SET NULL on delete) or
    that the found rows do not hold ends the walk.
    """
    seen = {vote.id}
    while vote.parent_vote_id is not None and vote.parent_vote_id in by_id:
        vote = by_id[vote.parent_vote_id]
        if vote.id in seen:  # a cycle cannot come from the API; stop all the same
            break
        seen.add(vote.id)
    return vote.id


async def erase_candidacies(session: AsyncSession, principal_id: UUID) -> list[ErasedCandidacy]:
    """Replace the name of each candidacy of a principal who was not elected (no commit).

    The ballots, the candidate ids and ``election_result`` stay, so the tally does not
    change. The account link (``principalId``) stays as a pseudonym, as the ``sub``
    of the principal does.

    Returns:
        The elections whose candidate list changed, each with its config before the
        change, so the caller can update the copies in the protocol text.
    """
    principal = str(principal_id)
    # The row lock waits for a parallel close, lot or runoff of the same election, so
    # the decision below reads the final result and a new runoff copies the new name.
    # The later rounds lock first, in the order of the cancel of a runoff.
    votes = (
        await session.scalars(
            select(Vote)
            .where(
                Vote.kind == ELECTION,
                Vote.config.contains({"candidates": [{"principalId": principal}]}),
            )
            .order_by(Vote.round.desc(), Vote.id)
            .with_for_update()
        )
    ).all()
    by_id = {vote.id: vote for vote in votes}
    elected_roots: set[UUID] = set()
    for vote in votes:
        candidate = _candidacy(vote, principal)
        if candidate is not None and _elected_in(vote, str(candidate.get("id"))):
            elected_roots.add(_root_of(vote, by_id))
    changed: list[ErasedCandidacy] = []
    for vote in votes:
        candidate = _candidacy(vote, principal)
        if candidate is None or _root_of(vote, by_id) in elected_roots:
            continue
        if candidate.get("name") == ERASED_CANDIDATE_NAME:
            continue  # erased before
        old_config = vote.config
        # A new dict: the JSONB column sees the change only on a new value.
        vote.config = {
            **old_config,
            "candidates": [
                {**c, "name": ERASED_CANDIDATE_NAME} if c is candidate else c
                for c in old_config["candidates"]
            ],
        }
        changed.append(ErasedCandidacy(vote=vote, old_config=old_config))
    return changed
