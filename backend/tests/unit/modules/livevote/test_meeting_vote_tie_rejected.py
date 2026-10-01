"""O18: a meeting vote has no casting vote, so a tie is ``rejected``.

The meeting-vote route stores ``tieBreak=rejected`` itself. ``MeetingVoteOpenBody`` has
no ``tieBreak``, so a client value has no effect. An application vote outside a
meeting keeps its own ``tieBreak``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.livevote.router import (
    get_agenda_service,
    get_attendance_service,
    get_meeting_service,
    get_voting_service,
)
from app.modules.livevote.schemas import MeetingVoteOpenBody
from app.modules.voting import tally as tally_mod
from app.shared.config_schemas import VoteConfig
from tests.unit.modules.livevote.test_livevote_cov import (
    _FakeAgendaService,
    _FakeAttendanceService,
    _FakeMeetingService,
    _FakeVotingService,
    _meeting_out,
)


@pytest.fixture
def fakes() -> dict[str, Any]:
    return {
        "meeting": _FakeMeetingService(),
        "attendance": _FakeAttendanceService(),
        "agenda": _FakeAgendaService(),
        "voting": _FakeVotingService(),
    }


@pytest.fixture
def client(fakes: dict[str, Any]) -> TestClient:
    app: FastAPI = create_app()
    app.dependency_overrides[get_meeting_service] = lambda: fakes["meeting"]
    app.dependency_overrides[get_attendance_service] = lambda: fakes["attendance"]
    app.dependency_overrides[get_agenda_service] = lambda: fakes["agenda"]
    app.dependency_overrides[get_voting_service] = lambda: fakes["voting"]
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="lead")
    return TestClient(app)


def test_open_body_has_no_tie_break() -> None:
    assert "tie_break" not in MeetingVoteOpenBody.model_fields


@pytest.mark.parametrize("application", [False, True])
def test_meeting_vote_stores_tie_break_rejected(
    client: TestClient, fakes: dict[str, Any], application: bool
) -> None:
    if application:
        fakes["agenda"].item_row = SimpleNamespace(id=uuid4(), application_id=uuid4())
    fakes["meeting"]._meeting_out = _meeting_out(status="live", can_manage_votes=True)
    r = client.post(
        f"/api/meetings/{uuid4()}/votes",
        # A client tieBreak is not part of the body and has no effect.
        json={"agendaItemId": str(uuid4()), "tieBreak": "passed"},
    )
    assert r.status_code == 200
    config: VoteConfig = fakes["voting"].last_payload.config
    assert config.tie_break == "rejected"


def test_tie_with_rejected_tie_break_is_rejected() -> None:
    config = VoteConfig.model_validate(
        {"options": ["yes", "no", "abstain"], "majorityRule": "simple", "tieBreak": "rejected"}
    )
    outcome = tally_mod.result(config, {"yes": 2, "no": 2, "abstain": 1}, 5)
    assert outcome.result == "rejected"


def test_application_vote_keeps_its_tie_break() -> None:
    config = VoteConfig.model_validate(
        {"options": ["yes", "no"], "majorityRule": "simple", "tieBreak": "tie"}
    )
    assert tally_mod.result(config, {"yes": 1, "no": 1}, 2).result == "tie"
