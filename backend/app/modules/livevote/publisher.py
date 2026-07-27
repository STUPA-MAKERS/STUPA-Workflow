"""Live-vote publisher seam for the voting module.

The voting REST endpoints control the session. They must publish the matching
WebSocket events on the `meeting:{id}` channel. The voting module depends on
this leaf protocol only, so it does not couple to the broker. This keeps the
imports free of a cycle.

The default is `NullPublisher`, which does nothing. `create_app` injects the
broker-backed `app.modules.livevote.service.BrokerPublisher`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from fastapi import Request

if TYPE_CHECKING:
    from app.modules.voting.schemas import VoteClosed, VoteOut


class MeetingPublisher(Protocol):
    """Publish live-vote events.

    A vote that is not bound to a meeting produces no event.
    """

    async def vote_opened(self, vote: VoteOut) -> None: ...

    async def vote_tally(self, vote: VoteOut) -> None: ...

    async def vote_closed(self, vote: VoteClosed) -> None: ...

    async def vote_cancelled(self, vote: VoteOut) -> None: ...


class NullPublisher:
    """Default without a broker.

    The publisher drops the events. The vote API keeps working.
    """

    async def vote_opened(self, vote: VoteOut) -> None:
        return None

    async def vote_tally(self, vote: VoteOut) -> None:
        return None

    async def vote_closed(self, vote: VoteClosed) -> None:
        return None

    async def vote_cancelled(self, vote: VoteOut) -> None:
        return None


def get_meeting_publisher(request: Request) -> MeetingPublisher:
    """Return the publisher from the app state.

    Without a broker the function falls back to `NullPublisher`.
    """
    publisher = getattr(request.app.state, "meeting_publisher", None)
    if publisher is None:
        return NullPublisher()
    return publisher
