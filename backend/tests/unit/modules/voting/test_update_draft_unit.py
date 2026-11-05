"""VotingService.update_draft: the change of a prepared meeting vote, without a database.

Only a draft of the named meeting changes. The kind follows the new config, the proposal
needs an application and an amount that fits it, and the change writes ``vote_update``
with id references only.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.applications.decision import DecisionIn
from app.modules.voting import service as voting_service
from app.modules.voting.schemas import VoteCreateInternal
from app.modules.voting.service import VotingService
from app.shared.config_schemas import ElectionConfig, PollConfig, VoteConfig
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

GID = UUID("00000000-0000-0000-0000-00000000a1b2")
MID = uuid4()

_MOTION = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "absolute", "secret": True}
)
_ELECTION = ElectionConfig.model_validate(
    {"seats": 1, "candidates": [{"id": "c1", "name": "A"}, {"id": "c2", "name": "B"}]}
)
_POLL = PollConfig.model_validate(
    {
        "mode": "single",
        "options": [{"id": "o1", "label": "Ja"}, {"id": "o2", "label": "Nein"}],
        "secret": False,
    }
)


class _Session:
    def __init__(self) -> None:
        self.committed = 0

    async def commit(self) -> None:
        self.committed += 1


def _vote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "meeting_id": MID,
        "agenda_item_id": uuid4(),
        "application_id": None,
        "status": "draft",
        "kind": "motion",
        "question": "Alt?",
        "config": {},
        "eligible_count": 3,
        "proposal": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _payload(config: Any, **over: Any) -> VoteCreateInternal:
    body: dict[str, Any] = {
        "config": config,
        "eligibleGroup": str(GID),
        "question": "Neu?",
        "eligibleCount": 7,
    }
    body.update(over)
    return VoteCreateInternal.model_validate(body)


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _record(session: Any, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(voting_service, "audit_record", _record)
    return calls


def _service(vote: SimpleNamespace, app: Any = None) -> tuple[VotingService, _Session]:
    session = _Session()
    svc = VotingService(session)  # type: ignore[arg-type]

    async def _get_vote(vote_id: UUID, *, for_update: bool = False) -> Any:
        assert for_update
        return vote

    async def _get_application(application_id: UUID) -> Any:
        return app

    svc._get_vote = _get_vote  # type: ignore[method-assign]
    svc._get_application = _get_application  # type: ignore[method-assign]
    return svc, session


async def test_update_motion_replaces_the_question_and_the_rules(
    audits: list[dict[str, Any]],
) -> None:
    vote = _vote()
    svc, session = _service(vote)
    out = await svc.update_draft(vote.id, _payload(_MOTION), meeting_id=MID, actor="lead")
    assert out is vote
    assert vote.kind == "motion"
    assert vote.question == "Neu?"
    assert vote.config["majorityRule"] == "absolute"
    assert vote.eligible_count == 7
    assert vote.proposal is None
    assert session.committed == 1
    [entry] = audits
    assert entry["action"] == "vote_update"
    assert entry["actor"] == "lead"
    assert entry["data"] == {
        "kind": "motion",
        "meetingId": str(MID),
        "agendaItemId": str(vote.agenda_item_id),
        "applicationId": None,
    }


@pytest.mark.parametrize(("config", "kind"), [(_ELECTION, "election"), (_POLL, "poll")])
async def test_update_changes_the_kind(
    audits: list[dict[str, Any]], config: Any, kind: str
) -> None:
    vote = _vote(agenda_item_id=None)
    svc, _ = _service(vote)
    await svc.update_draft(vote.id, _payload(config), meeting_id=MID)
    assert vote.kind == kind
    assert audits[0]["data"]["kind"] == kind
    assert audits[0]["data"]["agendaItemId"] is None


async def test_update_of_an_application_vote_checks_the_proposal(
    audits: list[dict[str, Any]],
) -> None:
    vote = _vote(application_id=uuid4())
    app = SimpleNamespace(amount=Decimal("500"))
    svc, _ = _service(vote, app)
    proposal = DecisionIn.model_validate({"approvedAmount": "400.00", "conditions": ["Beleg"]})
    await svc.update_draft(vote.id, _payload(_MOTION, proposal=proposal), meeting_id=MID)
    assert vote.proposal == proposal.to_json()
    assert audits[0]["data"]["applicationId"] == str(vote.application_id)
    too_much = DecisionIn.model_validate({"approvedAmount": "900.00", "conditions": []})
    with pytest.raises(ValidationProblem):
        await svc.update_draft(vote.id, _payload(_MOTION, proposal=too_much), meeting_id=MID)


async def test_update_refuses_a_proposal_without_application(
    audits: list[dict[str, Any]],
) -> None:
    vote = _vote()
    svc, session = _service(vote)
    proposal = DecisionIn.model_validate({"approvedAmount": None, "conditions": ["x"]})
    with pytest.raises(ValidationProblem):
        await svc.update_draft(vote.id, _payload(_MOTION, proposal=proposal), meeting_id=MID)
    assert session.committed == 0
    assert audits == []


async def test_update_refuses_a_vote_of_another_meeting(audits: list[dict[str, Any]]) -> None:
    vote = _vote(meeting_id=uuid4())
    svc, _ = _service(vote)
    with pytest.raises(NotFoundError):
        await svc.update_draft(vote.id, _payload(_MOTION), meeting_id=MID)


@pytest.mark.parametrize("status", ["open", "closed", "cancelled"])
async def test_update_refuses_a_vote_that_is_no_draft(
    audits: list[dict[str, Any]], status: str
) -> None:
    vote = _vote(status=status)
    svc, _ = _service(vote)
    with pytest.raises(ConflictError) as err:
        await svc.update_draft(vote.id, _payload(_MOTION), meeting_id=MID)
    assert err.value.code == "vote_not_editable"
    assert audits == []
