"""WebSocket-Nachrichten-Schemata (api.md §4, Live-Vote).

Getrennte Modelle für **Server→Client** (``meeting_state``, ``vote_opened``,
``vote_tally``, ``vote_closed``, ``error``) und **Client→Server** (``cast``,
``subscribe``). Jede Nachricht ist JSON ``{"type": …, …}``; ``type`` ist der
Discriminator. Die Modelle sind die Single-Source des WS-Contracts (Schema-Test)
und werden im Handler zum Validieren der eingehenden bzw. Serialisieren der
ausgehenden Nachrichten genutzt.

**Beamer/Geheimhaltung (requirements N1a):** ``vote_tally``/``vote_closed`` tragen
ausschließlich Aggregate (``counts``/``quorumMet``/``leading``/``result``) — **nie**
Wähler-Identitäten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; per Feldname befüllbar (wie übriges API)."""

    model_config = ConfigDict(populate_by_name=True)

    def dump(self) -> dict[str, object]:
        """JSON-fähiges Dict (camelCase, Enums/UUID als String) für ``send_json``."""
        return self.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------- #
# Server → Client
# --------------------------------------------------------------------------- #
class MeetingStateEvent(_CamelModel):
    """Aktueller Sitzungs-Zustand (Beamer + Voter)."""

    type: Literal["meeting_state"] = "meeting_state"
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    status: Literal["planned", "live", "closed"]


class VoteOpenedEvent(_CamelModel):
    """Abstimmung geöffnet — UI schaltet frei."""

    type: Literal["vote_opened"] = "vote_opened"
    vote_id: UUID = Field(alias="voteId")
    application_id: UUID = Field(alias="applicationId")
    options: list[str]
    closes_at: datetime | None = Field(default=None, alias="closesAt")


class VoteTallyEvent(_CamelModel):
    """Live-Zwischenstand — **nur Aggregate, keine Namen** (requirements N1a)."""

    type: Literal["vote_tally"] = "vote_tally"
    vote_id: UUID = Field(alias="voteId")
    counts: dict[str, int]
    eligible: int
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None


class VoteClosedEvent(_CamelModel):
    """Abstimmung geschlossen — Endergebnis (aggregiert)."""

    type: Literal["vote_closed"] = "vote_closed"
    vote_id: UUID = Field(alias="voteId")
    result: Literal["passed", "rejected", "tie"]
    counts: dict[str, int]


class ErrorEvent(_CamelModel):
    """Fehler am WS (z. B. ``not_eligible``, ``read_only``, ``not_open``)."""

    type: Literal["error"] = "error"
    code: str


# --------------------------------------------------------------------------- #
# Client → Server
# --------------------------------------------------------------------------- #
class CastMessage(_CamelModel):
    """Stimmabgabe über den WS (serverseitig: group + unique + open + Lock)."""

    type: Literal["cast"]
    vote_id: UUID = Field(alias="voteId")
    choice: str = Field(min_length=1)


class SubscribeMessage(_CamelModel):
    """Initialen/aktuellen State anfordern (Reconnect-Konsistenz)."""

    type: Literal["subscribe"]
