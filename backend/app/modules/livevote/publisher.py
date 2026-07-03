"""Live-vote publisher seam for the voting module.

Session control runs through the voting REST endpoints, which must publish the
matching WS events on the ``meeting:{id}`` channel. The voting module depends
only on this leaf protocol so it doesn't couple to the broker (no import cycle).
Default is :class:`NullPublisher` (no-op); the broker-backed implementation
(:class:`app.modules.livevote.service.BrokerPublisher`) is injected in
``create_app``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from fastapi import Request

if TYPE_CHECKING:
    from app.modules.voting.schemas import VoteClosed, VoteOut


class MeetingPublisher(Protocol):
    """Publishes live-vote events; no-op when the vote isn't bound to a meeting."""

    async def vote_opened(self, vote: VoteOut) -> None: ...

    async def vote_tally(self, vote: VoteOut) -> None: ...

    async def vote_closed(self, vote: VoteClosed) -> None: ...

    async def vote_cancelled(self, vote: VoteOut) -> None: ...


class NullPublisher:
    """Default without a broker: drops events (the vote API stays functional)."""

    async def vote_opened(self, vote: VoteOut) -> None:
        return None

    async def vote_tally(self, vote: VoteOut) -> None:
        return None

    async def vote_closed(self, vote: VoteClosed) -> None:
        return None

    async def vote_cancelled(self, vote: VoteOut) -> None:
        return None


def get_meeting_publisher(request: Request) -> MeetingPublisher:
    """Publisher from app state; falls back to :class:`NullPublisher` without a broker."""
    publisher = getattr(request.app.state, "meeting_publisher", None)
    if publisher is None:
        return NullPublisher()
    return publisher
