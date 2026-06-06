"""Live-Vote-Publisher-Anschluss für das Voting-Modul (flows §5).

Die Sitzungs-Steuerung läuft über die bestehenden Voting-REST-Endpunkte
(``POST /votes/{id}/open|close``); diese müssen die passenden WS-Events auf den
Kanal ``meeting:{id}`` veröffentlichen. Damit das Voting-Modul **nicht** auf den
Broker/Live-Vote koppelt (und kein Import-Zyklus entsteht), hängt es nur an diesem
leaf-Protokoll. Default ist :class:`NullPublisher` (no-op) — die echte,
Broker-gestützte Implementierung wird in ``create_app`` injiziert
(:class:`app.modules.livevote.service.BrokerPublisher`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from fastapi import Request

if TYPE_CHECKING:
    from app.modules.voting.schemas import VoteClosed, VoteOut


class MeetingPublisher(Protocol):
    """Veröffentlicht Live-Vote-Events; no-op, falls der Vote keiner Sitzung hängt."""

    async def vote_opened(self, vote: VoteOut) -> None: ...

    async def vote_closed(self, vote: VoteClosed) -> None: ...


class NullPublisher:
    """Default ohne Broker: verwirft Events (Vote-API bleibt funktionsfähig)."""

    async def vote_opened(self, vote: VoteOut) -> None:
        return None

    async def vote_closed(self, vote: VoteClosed) -> None:
        return None


def get_meeting_publisher(request: Request) -> MeetingPublisher:
    """Publisher aus dem App-State (Lifespan); ohne Broker → :class:`NullPublisher`."""
    publisher = getattr(request.app.state, "meeting_publisher", None)
    if publisher is None:
        return NullPublisher()
    return publisher
