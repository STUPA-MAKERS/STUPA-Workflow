"""API-Schemata des Voting-Moduls (T-15, api.md »voting«)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.shared.config_schemas import VoteConfig


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class VoteCreate(_CamelModel):
    """``POST /applications/{id}/votes`` — Abstimmung anlegen (status ``draft``)."""

    config: VoteConfig
    eligible_group: str = Field(alias="eligibleGroup", min_length=1)
    # Beschlussfrage (»Worüber wird abgestimmt?«) — fürs Protokoll (#Meetings).
    question: str | None = None
    # Maßgebliche Zahl der Stimmberechtigten (Beschlussfähigkeits-Basis aus dem
    # Roster der Gruppe/des Gremiums) — **Nenner** des Prozent-Quorums. NICHT aus
    # eingeloggten Usern abgeleitet (das wäre fail-open). Pflicht für Prozent-Quorum;
    # fehlt sie dort, ist das Quorum fail-closed nie erfüllt.
    eligible_count: int | None = Field(default=None, alias="eligibleCount", ge=0)
    opens_state_id: UUID | None = Field(default=None, alias="opensStateId")
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result_branch_transition_id: UUID | None = Field(
        default=None, alias="resultBranchTransitionId"
    )

    @model_validator(mode="after")
    def _percent_quorum_needs_eligible(self) -> VoteCreate:
        """Prozent-Quorum braucht eine maßgebliche Stimmberechtigten-Zahl (fail-closed)."""
        quorum = self.config.quorum
        if quorum is not None and quorum.type == "percent" and self.eligible_count is None:
            raise ValueError(
                "eligibleCount is required when a percent quorum is configured"
            )
        return self


class BallotIn(_CamelModel):
    """``POST /votes/{id}/ballot`` — Stimme abgeben (``choice`` ∈ ``config.options``)."""

    choice: str = Field(min_length=1)


class TallyOut(_CamelModel):
    """Aggregiertes Zwischen-/Endergebnis (api.md). Bei ``secret`` nur ``counts``."""

    counts: dict[str, int]
    eligible: int
    # Teilnahme-Fortschritt (immer sichtbar, auch geheim/verdeckt): wie viele der
    # **anwesenden** Mitglieder schon abgestimmt haben (#vote-progress).
    voted: int = 0
    present: int = 0
    # ``counts``/``leading`` sind nur sichtbar, wenn ``revealed`` — d. h. geschlossen
    # **oder** (nicht geheim **und** alle Anwesenden haben abgestimmt). Sonst verdeckt.
    revealed: bool = True
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None
    result: Literal["passed", "rejected", "tie"] | None = None
    # Warum scheiterte die Abstimmung? ``quorum`` = Quorum verfehlt (fail-closed),
    # ``majority`` = Quorum erreicht, aber Mehrheit verfehlt. ``None`` solange offen
    # oder bei ``passed``/``tie``.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )


class VoteOut(_CamelModel):
    """Vote-State + Tally (``GET /votes/{id}``)."""

    id: UUID
    # None = generische Beschlussfrage (Freitext-TOP), kein Antrag.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    # Sitzung, an die der Vote hängt (Live-Vote, T-16); None bei reinem Async-Vote.
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    question: str | None = None
    eligible_group: str = Field(alias="eligibleGroup")
    config: VoteConfig
    # ``cancelled``: Antrag hat den vote-State manuell verlassen (Wahl abgebrochen).
    status: Literal["draft", "open", "closed", "cancelled"]
    opens_at: datetime | None = Field(default=None, alias="opensAt")
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result: Literal["passed", "rejected", "tie"] | None = None
    secret: bool
    tally: TallyOut


class BallotAccepted(_CamelModel):
    """Antwort auf eine angenommene Stimme."""

    status: Literal["cast", "changed"]


class VoteClosed(_CamelModel):
    """Ergebnis des Schließens (``POST /votes/{id}/close``)."""

    id: UUID
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    result: Literal["passed", "rejected", "tie"]
    tally: TallyOut
    fired_transition_id: UUID | None = Field(
        default=None, alias="firedTransitionId"
    )
    new_state_id: UUID | None = Field(default=None, alias="newStateId")
