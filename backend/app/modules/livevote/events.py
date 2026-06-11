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

**Geheime Abstimmung (``secret=true``), Regel »Counts erst bei Close« (api.md §4):**
Solange ein geheimer Vote **offen** ist, darf der Live-Feed (Beamer **und** Voter)
keinen Zwischenstand je Option preisgeben. ``vote_tally`` trägt dann nur die
**Teilnahme** (``cast`` von ``eligible``) — ``counts`` ist leer ``{}`` und ``leading``
``null``. Erst ``vote_closed`` liefert die vollen Aggregate. Das spiegelt die
REST-Regel ``showBars = !secret || isClosed``. ``secret`` reist in ``vote_opened`` und
``vote_tally`` mit, damit das FE (T-32) die Balken von Anfang an korrekt ausblendet.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.modules.voting.schemas import VoteOut


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


class ViewersEvent(_CamelModel):
    """Wer hat die Sitzungs-Seite gerade offen (#live-viewers) — Anzeigenamen,
    dedupliziert je Nutzer. Geht an den Voter-Kanal (nicht an den Beamer)."""

    type: Literal["viewers"] = "viewers"
    viewers: list[str]


class VoteOpenedEvent(_CamelModel):
    """Abstimmung geöffnet — UI schaltet frei."""

    type: Literal["vote_opened"] = "vote_opened"
    vote_id: UUID = Field(alias="voteId")
    # None = generische Beschlussfrage (Freitext-TOP), kein Antrag.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    # Beschlussfrage (»Worüber wird abgestimmt?«) — fürs Live-Dialog/Beamer.
    question: str | None = None
    options: list[str]
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    # Geheime Abstimmung → FE blendet Live-Balken aus (showBars = !secret || isClosed).
    secret: bool = False


class VoteTallyEvent(_CamelModel):
    """Live-Zwischenstand — **nur Aggregate, keine Namen** (requirements N1a).

    Bei einem **offenen geheimen** Vote bleibt ``counts`` leer und ``leading`` ``null``
    (kein Zwischenstand); nur die Teilnahme (``cast`` von ``eligible``) ist sichtbar.
    Über :meth:`from_vote` konstruieren, damit diese Regel an **einer** Stelle gilt.
    """

    type: Literal["vote_tally"] = "vote_tally"
    vote_id: UUID = Field(alias="voteId")
    # Stimmen je Option — leer ``{}`` solange der Vote geheim **und** offen ist.
    # Stimmen je Option — leer ``{}`` solange der Tally **verdeckt** ist (siehe ``revealed``).
    counts: dict[str, int]
    # Abgegebene Stimmen (Teilnahme). Immer sichtbar (auch verdeckt): "N von M anwesend".
    cast: int = 0
    eligible: int
    # Anwesende Mitglieder (Reveal-Nenner) + ob die Choice-Counts sichtbar sind.
    present: int = 0
    revealed: bool = True
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None
    # Geheime Abstimmung → FE blendet Live-Balken aus (showBars = !secret || isClosed).
    secret: bool = False

    @classmethod
    def from_vote(cls, vote: VoteOut) -> VoteTallyEvent:
        """Tally-Event aus einem Vote bauen. Die Reveal-Regel (geschlossen **oder** nicht
        geheim **und** alle Anwesenden gestimmt) ist bereits im Service auf ``tally``
        angewandt (``counts``/``leading`` verdeckt) — hier nur die Felder durchreichen.
        ``cast`` kommt aus ``tally.voted`` (echte Teilnahme, auch wenn ``counts`` verdeckt).
        ``revealed`` ist hier die Schutz-Schranke: bei ``False`` reisen **keine**
        Choice-Counts/``leading`` mit (defensiv, falls der Service sie nicht schon leerte)."""
        revealed = vote.tally.revealed
        return cls(
            voteId=vote.id,
            counts=vote.tally.counts if revealed else {},
            cast=vote.tally.voted,
            eligible=vote.tally.eligible,
            present=vote.tally.present,
            revealed=revealed,
            quorumMet=vote.tally.quorum_met,
            leading=vote.tally.leading if revealed else None,
            secret=vote.secret,
        )


class VoteClosedEvent(_CamelModel):
    """Abstimmung geschlossen — Endergebnis (aggregiert)."""

    type: Literal["vote_closed"] = "vote_closed"
    vote_id: UUID = Field(alias="voteId")
    result: Literal["passed", "rejected", "tie"]
    counts: dict[str, int]
    # Warum scheiterte die Abstimmung (nur bei ``rejected``): ``quorum`` = Quorum
    # verfehlt, ``majority`` = Mehrheit verfehlt. ``None`` bei ``passed``/``tie``.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )


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
