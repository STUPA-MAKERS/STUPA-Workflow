"""Erasure of a person from the candidate lists of the elections (DSGVO Art. 17).

An election (``vote.kind = 'election'``) keeps the name of each candidate in
``vote.config.candidates``; the ballots and ``election_result`` name the candidates by
their id only. The erasure of a principal replaces the name of each candidacy of that
principal with ``ERASED_CANDIDATE_NAME``, unless the principal was elected: the result
of an election is a documented resolution, so an elected candidate keeps the name. The
candidate also gets the marker ``erased: true``: the UI shows a label in the language of
the viewer, and ``ERASED_CANDIDATE_NAME`` stays the stored name for the German protocol
and for a client that does not know the marker.

A candidacy counts as elected when the closed result of a vote of the same election
lists the candidate. An election is the first round and its runoffs: a runoff copies
the candidates with their ``principalId``, so each round carries the candidacy and a
win in a runoff also keeps the name in the earlier rounds. An election that is not
decided (open, a lot that is pending, a runoff that is pending) elected nobody yet, so
its candidacy gets the placeholder.

The function finds a candidacy by its ``principalId`` only. A candidate without an
account link has a name only, and the function never matches a name. The account
merge (``admin/principal_merge.py``) does not rewrite ``principalId`` in the stored
candidate lists, so a candidacy of an account that was merged into the erased one
still names the old account: the function matches the erased id and the id of each
account whose ``merged_into`` names it (a merge chain has one step only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal
from app.modules.voting.election import ELECTION
from app.modules.voting.models import Vote

#: The name that replaces the name of an erased candidate who was not elected.
ERASED_CANDIDATE_NAME = "Gelöscht"
#: The marker key of an erased candidate in ``vote.config.candidates[]`` (see
#: ``ElectionCandidate.erased``).
ERASED_KEY = "erased"

#: The bound of the passes that look for rounds a parallel runoff added.
_MAX_PASSES = 5


@dataclass(frozen=True, slots=True)
class ErasedCandidacy:
    """One election whose candidate list changed: the vote and its config before."""

    vote: Vote
    old_config: dict[str, Any]


def _candidacies(vote: Vote, principals: frozenset[str]) -> list[dict[str, Any]]:
    """Return the stored candidates of ``vote`` that link one of ``principals``."""
    return [
        candidate
        for candidate in vote.config.get("candidates") or []
        if candidate.get("principalId") in principals
    ]


def _unerased(vote: Vote, principals: frozenset[str]) -> list[dict[str, Any]]:
    """Return the candidacies of ``principals`` in ``vote`` that carry no erased marker."""
    return [
        candidate
        for candidate in _candidacies(vote, principals)
        if candidate.get(ERASED_KEY) is not True
    ]


def _erased_config(config: dict[str, Any], mine: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a new config whose candidates in ``mine`` carry the placeholder name."""
    return {
        **config,
        "candidates": [
            {**c, "name": ERASED_CANDIDATE_NAME, ERASED_KEY: True}
            if any(c is m for m in mine)
            else c
            for c in config["candidates"]
        ],
    }


def _elected_in(vote: Vote, candidate_id: str) -> bool:
    """Tell whether the closed result of ``vote`` elected ``candidate_id``."""
    stored = vote.election_result
    return (
        vote.status == "closed"
        and bool(stored)
        and candidate_id in (stored.get("elected") or [])
    )


def _root_of(vote: Vote, by_id: dict[UUID, Vote]) -> UUID:
    """Return the first round of the election of ``vote`` among the found rounds.

    Each runoff carries the candidacy of its parent, so the walk stays inside the
    found rows. A parent that is gone (``parent_vote_id`` is SET NULL on delete) or
    that the found rows do not hold ends the walk.

    A cycle cannot come from the API. The walk stops on one all the same.
    """
    return _walk_up(vote, by_id, frozenset({vote.id}))


def _walk_up(vote: Vote, by_id: dict[UUID, Vote], seen: frozenset[UUID]) -> UUID:
    """Follow the parents of ``vote`` inside ``by_id`` and stop at a round in ``seen``."""
    parent = by_id.get(vote.parent_vote_id) if vote.parent_vote_id is not None else None
    return (
        vote.id
        if parent is None
        else (parent.id if parent.id in seen else _walk_up(parent, by_id, seen | {parent.id}))
    )


async def _principal_ids(session: AsyncSession, principal_id: UUID) -> frozenset[str]:
    """Return the erased id and the ids of the accounts merged into it, as strings."""
    merged = (
        await session.scalars(select(Principal.id).where(Principal.merged_into == principal_id))
    ).all()
    return frozenset({str(principal_id), *(str(m) for m in merged)})


async def _locked_elections(session: AsyncSession, principals: frozenset[str]) -> list[Vote]:
    """Lock and return every election round that carries a candidacy of ``principals``.

    The row lock waits for a parallel close, lot or runoff of the same election, so
    the decision reads the final result and a later runoff copies the new name. The
    later rounds lock first, in the order of the cancel of a runoff.

    A round that another transaction inserted while this select waited for
    the lock of its parent is not in the snapshot of the select (READ COMMITTED). Its
    transaction has committed once the lock is granted, so a new select sees it. The
    function selects again until a pass finds no new round, at most ``_MAX_PASSES``
    times.
    """
    match = or_(
        *(Vote.config.contains({"candidates": [{"principalId": p}]}) for p in sorted(principals))
    )
    return await _lock_rounds(session, match, (), _MAX_PASSES)


async def _lock_rounds(
    session: AsyncSession, match: ColumnElement[bool], found: tuple[Vote, ...], passes: int
) -> list[Vote]:
    """Lock the matching rounds that ``found`` does not hold, for at most ``passes`` passes.

    A pass that finds no new round ends the search.
    """
    base = select(Vote).where(Vote.kind == ELECTION, match)
    stmt = base.where(Vote.id.not_in(sorted({v.id for v in found}))) if found else base
    new = (
        (await session.scalars(stmt.order_by(Vote.round.desc(), Vote.id).with_for_update())).all()
        if passes > 0
        else ()
    )
    return await _lock_rounds(session, match, (*found, *new), passes - 1) if new else list(found)


async def erase_candidacies(session: AsyncSession, principal_id: UUID) -> list[ErasedCandidacy]:
    """Replace the name of each candidacy of a principal who was not elected (no commit).

    The candidate gets ``ERASED_CANDIDATE_NAME`` and the marker ``erased: true``. A
    candidate that carries the marker is not changed again.

    The ballots, the candidate ids and ``election_result`` stay, so the tally does not
    change. The account link (``principalId``) stays as a pseudonym, as the ``sub``
    of the principal does. A candidacy of an account merged into the principal counts
    as a candidacy of the principal.

    The config gets a new dict, because the JSONB column sees a change only on a new
    value.

    Returns:
        The elections whose candidate list changed, each with its config before the
        change, so the caller can update the copies in the protocol text.
    """
    principals = await _principal_ids(session, principal_id)
    votes = await _locked_elections(session, principals)
    by_id = {vote.id: vote for vote in votes}
    elected_roots = frozenset(
        _root_of(vote, by_id)
        for vote in votes
        if any(
            _elected_in(vote, str(candidate.get("id")))
            for candidate in _candidacies(vote, principals)
        )
    )
    changed = [
        ErasedCandidacy(vote=vote, old_config=vote.config)
        for vote in votes
        if _unerased(vote, principals) and _root_of(vote, by_id) not in elected_roots
    ]
    for entry in changed:
        entry.vote.config = _erased_config(entry.old_config, _unerased(entry.vote, principals))
    return changed
