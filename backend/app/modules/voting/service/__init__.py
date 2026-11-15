"""Voting service: create -> open -> cast -> close (or cancel).

Every vote is secret. Race safety: the DB enforces one ballot per voter. A ballot
never changes after the cast. ``voted_marker`` (UNIQUE) records 'has voted' with
``INSERT ... ON CONFLICT (vote_id, voter_sub) DO NOTHING``, and an empty ``RETURNING``
means a second cast -> 409 ``already_voted``. The choice lands without an identity in
``secret_ballot``.

Close and cancel set ``closed_at``. Open, close and cancel write an audit entry.
A close always ends the vote: when the pass or fail transition of the
application cannot fire, the close still commits, writes ``vote_branch_blocked`` and
returns ``branchFired=false``.

RBAC is fail-closed and gremium-scoped. ``vote.eligible_group`` holds the UUID of the
gremium that votes. A ``cast`` needs the gremium permission ``vote.cast`` there: only an
active gremium role with ``vote.cast`` writes the namespaced group key
``vote:<gremium_id>``. No global permission grants a vote right. The quorum denominator
(``MeetingRules.vote_eligible_count``) reads the same roster, and ``create`` stores it
as ``eligible_count``, so the counted set and the admitted set stay equal. A vote with a
free group key (an old row) admits nobody: the call gets 403.

The livevote imports are local, because the livevote modules import this module.

The package splits the service across modules, without a change of the logic.

``base`` holds the problem codes, the module helpers, the constructor, the locks and
the read helpers that every part uses.
``access`` holds the reads of a vote and the rights to read, cast and manage it.
``plan`` holds the locks and the steps of the votes on a version of a Haushaltsplan.
``delete`` holds the delete of votes.
``create`` holds the create, the change of a draft and the open.
``cast`` holds the cast of a ballot.
``close`` holds the close and the cancel, with the result and the branch of the Antrag.
``service`` holds the ``VotingService`` facade that combines the parts.

This module exports the facade and the public helpers again, so
``from app.modules.voting.service import VotingService`` keeps working. A test that
replaces a name which a part imports must replace it in the module of that part.
"""

from app.modules.voting.service.base import (
    ALREADY_VOTED,
    GUEST_VOTER_PREFIX,
    VOTE_GREMIUM_MISMATCH,
    Choice,
    guest_voter_sub,
    holds_gremium_vote_role,
    manages_votes_in_gremium,
    secret_only,
    vote_gremium_mismatch_error,
)
from app.modules.voting.service.service import VotingService

__all__ = [
    "ALREADY_VOTED",
    "Choice",
    "GUEST_VOTER_PREFIX",
    "VOTE_GREMIUM_MISMATCH",
    "VotingService",
    "guest_voter_sub",
    "holds_gremium_vote_role",
    "manages_votes_in_gremium",
    "secret_only",
    "vote_gremium_mismatch_error",
]
