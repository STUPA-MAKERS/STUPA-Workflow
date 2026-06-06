"""API-Schemata des Voting-Moduls (T-15, api.md »voting«)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.config_schemas import VoteConfig


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class VoteCreate(_CamelModel):
    """``POST /applications/{id}/votes`` — Abstimmung anlegen (status ``draft``)."""

    config: VoteConfig
    eligible_group: str = Field(alias="eligibleGroup", min_length=1)
    opens_state_id: UUID | None = Field(default=None, alias="opensStateId")
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result_branch_transition_id: UUID | None = Field(
        default=None, alias="resultBranchTransitionId"
    )


class BallotIn(_CamelModel):
    """``POST /votes/{id}/ballot`` — Stimme abgeben (``choice`` ∈ ``config.options``)."""

    choice: str = Field(min_length=1)


class TallyOut(_CamelModel):
    """Aggregiertes Zwischen-/Endergebnis (api.md). Bei ``secret`` nur ``counts``."""

    counts: dict[str, int]
    eligible: int
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None
    result: Literal["passed", "rejected", "tie"] | None = None


class VoteOut(_CamelModel):
    """Vote-State + Tally (``GET /votes/{id}``)."""

    id: UUID
    application_id: UUID = Field(alias="applicationId")
    eligible_group: str = Field(alias="eligibleGroup")
    config: VoteConfig
    status: Literal["draft", "open", "closed"]
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
    result: Literal["passed", "rejected", "tie"]
    tally: TallyOut
    fired_transition_id: UUID | None = Field(
        default=None, alias="firedTransitionId"
    )
    new_state_id: UUID | None = Field(default=None, alias="newStateId")
