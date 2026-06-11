"""Router-Tests Delegationen (#delegation-rework): Verdrahtung, 401, camelCase, Fehler.

Service ist gefaked (Endpunkt-Verhalten, nicht DB). Beweist: 401 ohne Session,
Statuscodes (200/201/204), camelCase-Serialisierung (inkl. Kontext/Status/Pool)
und problem+json bei 403/404/422.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.delegations.router import get_delegation_service
from app.modules.delegations.schemas import (
    DelegationOut,
    MeetingDelegationContext,
    RecipientOut,
    SubstituteOut,
    VoteDelegationStatus,
)
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)


def _out(**over) -> DelegationOut:  # noqa: ANN003
    base = dict(
        id=uuid4(),
        meeting_id=uuid4(),
        meeting_title="Sitzung",
        meeting_date="2026-06-20",
        gremium_id=uuid4(),
        gremium_name="StuPa",
        delegator_id=uuid4(),
        delegator_name="Me",
        delegate_id=uuid4(),
        delegate_name="Other",
        delegate_voting=True,
        via_pool=False,
        created_at=NOW,
        revocable=True,
        direction="outgoing",
    )
    base.update(over)
    return DelegationOut(**base)  # type: ignore[arg-type]


class _FakeService:
    async def list(self, actor, meeting_id=None):  # noqa: ANN001
        return [_out()]

    async def create(self, payload, actor):  # noqa: ANN001
        return _out(
            meeting_id=payload.meeting_id,
            delegate_id=payload.delegate_id,
            delegate_voting=payload.delegate_voting,
        )

    async def revoke(self, delegation_id, actor):  # noqa: ANN001
        if str(delegation_id).startswith("00000000"):
            raise NotFoundError("nope")
        if str(delegation_id).startswith("11111111"):
            raise ForbiddenError("not yours")
        return None

    async def meeting_context(self, meeting_id, actor):  # noqa: ANN001
        return MeetingDelegationContext(
            meeting_id=meeting_id,
            gremium_id=uuid4(),
            allow_vote_delegation=True,
            voting_delegation_enabled=False,
            delegation_allow_external=False,
            deadline=None,
            deadline_passed=False,
            meeting_started=False,
            can_delegate=True,
            my_delegation=None,
            incoming=[],
            recipients=[
                RecipientOut(
                    principal_id=uuid4(),
                    display_name="Other",
                    via_pool=True,
                    is_member=False,
                )
            ],
        )

    async def recipients(self, meeting_id, q, actor):  # noqa: ANN001
        return []

    async def vote_status(self, vote_id, actor):  # noqa: ANN001
        return VoteDelegationStatus(
            blocked=True,
            delegated_to_name="Other",
            exercising=False,
            delegated_by_name=None,
        )

    async def substitutes_list(self, gremium_id, actor):  # noqa: ANN001
        return [
            SubstituteOut(
                id=uuid4(),
                gremium_id=gremium_id,
                member_id=None,
                member_name=None,
                substitute_id=uuid4(),
                substitute_name="Sub",
            )
        ]

    async def substitute_create(self, payload, actor):  # noqa: ANN001
        return SubstituteOut(
            id=uuid4(),
            gremium_id=payload.gremium_id,
            member_id=payload.member_id,
            member_name=None,
            substitute_id=payload.substitute_id,
            substitute_name="Sub",
        )

    async def substitute_delete(self, substitute_id, actor):  # noqa: ANN001
        return None


class _RaisingService(_FakeService):
    async def create(self, payload, actor):  # noqa: ANN001
        raise ValidationProblem(
            "disabled", errors=[{"field": "delegateVoting", "msg": "disabled"}]
        )


def _client(principal: Principal | None, service: object | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_delegation_service] = lambda: service or _FakeService()
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app, raise_server_exceptions=False)


_MEMBER = Principal(sub="deleg", roles=["member"], permissions=set())


def test_list_requires_session_401() -> None:
    r = _client(None).get("/api/delegations")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")


def test_list_returns_camelcase() -> None:
    r = _client(_MEMBER).get("/api/delegations")
    assert r.status_code == 200
    item = r.json()[0]
    expected = {
        "meetingId",
        "meetingTitle",
        "gremiumId",
        "delegatorName",
        "delegateName",
        "delegateVoting",
        "viaPool",
        "revocable",
        "direction",
    }
    assert expected <= item.keys()


def test_create_returns_201_camelcase() -> None:
    mid, did = str(uuid4()), str(uuid4())
    body = {"meetingId": mid, "delegateId": did, "delegateVoting": True}
    r = _client(_MEMBER).post("/api/delegations", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["meetingId"] == mid
    assert data["delegateId"] == did
    assert data["delegateVoting"] is True


def test_create_validation_problem_is_problem_json() -> None:
    body = {"meetingId": str(uuid4()), "delegateId": str(uuid4())}
    r = _client(_MEMBER, _RaisingService()).post("/api/delegations", json=body)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


def test_create_malformed_body_is_422() -> None:
    r = _client(_MEMBER).post("/api/delegations", json={"meetingId": "not-a-uuid"})
    assert r.status_code == 422


def test_revoke_returns_204() -> None:
    r = _client(_MEMBER).delete(f"/api/delegations/{uuid4()}")
    assert r.status_code == 204


def test_revoke_unknown_404_problem_json() -> None:
    r = _client(_MEMBER).delete("/api/delegations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_revoke_foreign_403_problem_json() -> None:
    r = _client(_MEMBER).delete("/api/delegations/11111111-1111-1111-1111-111111111111")
    assert r.status_code == 403


def test_meeting_context_camelcase() -> None:
    r = _client(_MEMBER).get(f"/api/delegations/meetings/{uuid4()}/context")
    assert r.status_code == 200
    data = r.json()
    expected = {
        "meetingId",
        "allowVoteDelegation",
        "votingDelegationEnabled",
        "delegationAllowExternal",
        "deadlinePassed",
        "meetingStarted",
        "canDelegate",
        "myDelegation",
        "incoming",
        "recipients",
    }
    assert expected <= data.keys()
    assert data["recipients"][0]["viaPool"] is True


def test_vote_status_camelcase() -> None:
    r = _client(_MEMBER).get(f"/api/delegations/votes/{uuid4()}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["blocked"] is True
    assert data["delegatedToName"] == "Other"
    assert data["exercising"] is False


def test_recipients_requires_session_401() -> None:
    r = _client(None).get(f"/api/delegations/meetings/{uuid4()}/recipients?q=x")
    assert r.status_code == 401


def test_substitutes_list_camelcase() -> None:
    r = _client(_MEMBER).get(f"/api/delegations/substitutes?gremiumId={uuid4()}")
    assert r.status_code == 200
    item = r.json()[0]
    assert {"gremiumId", "memberId", "substituteId", "substituteName"} <= item.keys()


def test_substitute_create_201() -> None:
    gid, sid = str(uuid4()), str(uuid4())
    r = _client(_MEMBER).post(
        "/api/delegations/substitutes", json={"gremiumId": gid, "substituteId": sid}
    )
    assert r.status_code == 201
    data = r.json()
    assert data["gremiumId"] == gid
    assert data["substituteId"] == sid
    assert data["memberId"] is None


def test_substitute_delete_204() -> None:
    r = _client(_MEMBER).delete(f"/api/delegations/substitutes/{uuid4()}")
    assert r.status_code == 204
