"""The ``VotingService`` facade: the parts of the vote service in one class."""

from app.modules.voting.service.cast import VoteCastOps
from app.modules.voting.service.close import VoteCloseOps
from app.modules.voting.service.create import VoteCreateOps


class VotingService(VoteCreateOps, VoteCastOps, VoteCloseOps):
    """Vote service on one ``AsyncSession`` with an optional flow dispatcher."""
