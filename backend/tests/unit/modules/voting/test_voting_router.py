"""Voting router wiring (T-15): fail-closed auth and the problem+json contract.

`dependency_overrides` replaces the service. The integration suite covers the DB paths.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import NullActionDispatcher
from app.modules.voting.router import get_action_dispatcher, get_voting_service
from app.modules.voting.schemas import (
    BallotAccepted,
    TallyOut,
    VoteClosed,
    VoteOut,
)
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ForbiddenError

_CONFIG = VoteConfig.model_validate({"options": ["yes", "no"], "majorityRule": "simple"})
_TALLY = TallyOut(counts={"yes": 0, "no": 0}, eligible=0, quorumMet=True)


def _vote_out(status: str = "draft") -> VoteOut:
    return VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        eligibleGroup="stupa",
        config=_CONFIG,
        status=status,  # type: ignore[arg-type]
        secret=False,
        tally=_TALLY,
    )


class _FakeService:
    def __init__(self) -> None:
        self.cast_args: dict[str, object] | None = None

    async def assert_can_manage_group(self, eligible_group, meeting_id, principal):  # noqa: ANN001
        # Mirrors the real service gate (#AUD-027) on the router path. The admin role or
        # a global vote.manage passes. The integration test covers the per-Gremium
        # resolution against the DB. Everything else fails closed with a 403.
        if "admin" in principal.roles or principal.has("vote.manage"):
            return
        raise ForbiddenError("not allowed to manage this vote")

    async def assert_can_manage_vote(self, vote_id, principal):  # noqa: ANN001
        await self.assert_can_manage_group("stupa", None, principal)

    async def create(self, application_id, payload):  # noqa: ANN001
        return _vote_out("draft")

    async def open(self, vote_id, *, now):  # noqa: ANN001
        return _vote_out("open")

    async def get(self, vote_id):  # noqa: ANN001
        return _vote_out("open")

    async def get_scoped(self, vote_id, principal):  # noqa: ANN001
        # The real service holds the scope gate. This fake passes through like get().
        return await self.get(vote_id)

    async def cast(
        self, vote_id, principal, choice, *, now, as_delegation=False
    ):  # noqa: ANN001
        self.cast_args = {
            "vote_id": vote_id,
            "choice": choice,
            "sub": principal.sub,
            "as_delegation": as_delegation,
        }
        return BallotAccepted(status="cast")

    async def close(self, vote_id, principal):  # noqa: ANN001
        return VoteClosed(id=vote_id, result="passed", tally=_TALLY)

    async def cancel(self, vote_id):  # noqa: ANN001
        return _vote_out("cancelled")

    async def update(self, vote_id, payload, *, actor):  # noqa: ANN001
        from app.shared.errors import ConflictError

        if str(vote_id).startswith("00000000"):
            raise ConflictError("not a draft", code="vote_not_draft")
        self.updated = (vote_id, payload.question, actor)
        return _vote_out("draft")

    async def delete_standalone(self, vote_id, *, actor):  # noqa: ANN001
        from app.shared.errors import ConflictError

        if str(vote_id).startswith("00000000"):
            raise ConflictError("not a draft", code="vote_not_draft")
        self.deleted = (vote_id, actor)


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_voting_service] = lambda: fake_service
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_principal(app: FastAPI, *perms: str, groups: set[str] | None = None) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set(perms), groups=groups or set()
    )
    app.dependency_overrides[get_current_applicant] = lambda: None


# create, open and close: vote.manage.
def test_create_requires_auth_401(client: TestClient) -> None:
    assert client.post(f"/api/applications/{uuid4()}/votes", json={}).status_code == 401


def test_create_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.cast")  # not .manage
    r = client.post(
        f"/api/applications/{uuid4()}/votes",
        json={"config": _CONFIG.model_dump(by_alias=True), "eligibleGroup": "stupa"},
    )
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"


def test_create_ok(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.manage")
    r = client.post(
        f"/api/applications/{uuid4()}/votes",
        json={"config": _CONFIG.model_dump(by_alias=True), "eligibleGroup": "stupa"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


def test_open_ok(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.manage")
    r = client.post(f"/api/votes/{uuid4()}/open")
    assert r.status_code == 200
    assert r.json()["status"] == "open"


def test_close_ok(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.manage")
    r = client.post(f"/api/votes/{uuid4()}/close")
    assert r.status_code == 200
    assert r.json()["result"] == "passed"


def test_close_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.cast")
    assert client.post(f"/api/votes/{uuid4()}/close").status_code == 403


def test_open_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    # #AUD-027: open is gremium-scoped. An identity with vote.cast alone, and without a
    # global or per-Gremium vote.manage, must NOT open a vote.
    _as_principal(app, "vote.cast")
    r = client.post(f"/api/votes/{uuid4()}/open")
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"


def test_cancel_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    # #AUD-027: cancel is gremium-scoped, symmetric to open and close.
    _as_principal(app, "vote.cast")
    assert client.post(f"/api/votes/{uuid4()}/cancel").status_code == 403


def test_cancel_ok_broadcasts(app: FastAPI, client: TestClient) -> None:
    from app.modules.livevote.publisher import get_meeting_publisher

    class _Pub:
        def __init__(self) -> None:
            self.cancelled: list[object] = []

        async def vote_cancelled(self, vote: object) -> None:
            self.cancelled.append(vote)

    pub = _Pub()
    app.dependency_overrides[get_meeting_publisher] = lambda: pub
    _as_principal(app, "vote.manage")
    r = client.post(f"/api/votes/{uuid4()}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert len(pub.cancelled) == 1


# ballot: vote.cast. The service checks the group.
def test_ballot_requires_auth_401(client: TestClient) -> None:
    r = client.post(f"/api/votes/{uuid4()}/ballot", json={"choice": "yes"})
    assert r.status_code == 401


def test_ballot_gate_is_auth_only(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    # #delegation-rework: the gate checks authentication only. An external substitute
    # holds no global vote.cast. The service authorizes the cast through vote.cast plus
    # the group, or through the delegation row. Its own unit tests cover that.
    _as_principal(app, "vote.manage")  # not .cast
    r = client.post(f"/api/votes/{uuid4()}/ballot", json={"choice": "yes"})
    assert r.status_code == 200
    assert fake_service.cast_args is not None


def test_ballot_ok_passes_choice(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "vote.cast", groups={"stupa"})
    vote_id = uuid4()
    r = client.post(f"/api/votes/{vote_id}/ballot", json={"choice": "yes"})
    assert r.status_code == 200
    assert r.json()["status"] == "cast"
    assert fake_service.cast_args == {
        "vote_id": vote_id,
        "choice": "yes",
        "sub": "p",
        "as_delegation": False,
    }


def test_ballot_rejects_empty_choice_422(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.cast", groups={"stupa"})
    r = client.post(f"/api/votes/{uuid4()}/ballot", json={"choice": ""})
    assert r.status_code == 422


# get: every principal.
def test_get_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/votes/{uuid4()}").status_code == 401


def test_get_ok(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)  # logged in is enough
    r = client.get(f"/api/votes/{uuid4()}")
    assert r.status_code == 200


# DI factories and the OpenAPI contract.
def test_di_factories_build_real_objects() -> None:
    assert isinstance(get_action_dispatcher(), NullActionDispatcher)
    dispatcher = NullActionDispatcher()
    service = get_voting_service(session=object(), dispatcher=dispatcher)  # type: ignore[arg-type]
    assert isinstance(service, VotingService)
    assert service.dispatcher is dispatcher


def test_openapi_declares_voting_error_responses(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    ballot = spec["paths"]["/api/votes/{vote_id}/ballot"]["post"]
    assert {"400", "401", "403", "404", "409", "422"} <= set(ballot["responses"])
    assert "application/problem+json" in ballot["responses"]["409"]["content"]
    close = spec["paths"]["/api/votes/{vote_id}/close"]["post"]
    assert {"401", "403", "404", "409"} <= set(close["responses"])


def test_ballot_broadcasts_vote_tally(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """#vote-progress: cast broadcasts the live counter.

    Without the event, the "N of M voted" display stayed stale on every client until a
    reload.
    """
    from app.modules.livevote.publisher import get_meeting_publisher

    class _RecordingPublisher:
        def __init__(self) -> None:
            self.tallies: list[object] = []

        async def vote_opened(self, vote) -> None:  # noqa: ANN001
            return None

        async def vote_tally(self, vote) -> None:  # noqa: ANN001
            self.tallies.append(vote)

        async def vote_closed(self, vote) -> None:  # noqa: ANN001
            return None

    pub = _RecordingPublisher()
    app.dependency_overrides[get_meeting_publisher] = lambda: pub
    _as_principal(app, "vote.cast", groups={"stupa"})
    r = client.post(f"/api/votes/{uuid4()}/ballot", json={"choice": "yes"})
    assert r.status_code == 200
    assert len(pub.tallies) == 1  # a fresh state after the ballot


# DELETE /votes/{id}: gremium-scoped vote.manage, like open/close/cancel.


def test_delete_vote_requires_auth_401(client: TestClient) -> None:
    assert client.delete(f"/api/votes/{uuid4()}").status_code == 401


def test_delete_vote_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.cast")
    assert client.delete(f"/api/votes/{uuid4()}").status_code == 403


def test_delete_vote_204(app: FastAPI, client: TestClient, fake_service: _FakeService) -> None:
    _as_principal(app, "vote.manage")
    vid = uuid4()
    assert client.delete(f"/api/votes/{vid}").status_code == 204
    assert fake_service.deleted == (vid, "p")


def test_delete_vote_conflict_409(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.manage")
    r = client.delete("/api/votes/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")


# PATCH /votes/{id}: gremium-scoped vote.manage, like the delete.


def test_update_vote_requires_auth_401(client: TestClient) -> None:
    assert client.patch(f"/api/votes/{uuid4()}", json={}).status_code == 401


def test_update_vote_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.cast")
    r = client.patch(f"/api/votes/{uuid4()}", json={"question": "x"})
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"


def test_update_vote_ok(app: FastAPI, client: TestClient, fake_service: _FakeService) -> None:
    _as_principal(app, "vote.manage")
    vid = uuid4()
    r = client.patch(f"/api/votes/{vid}", json={"question": "Neue Frage"})
    assert r.status_code == 200
    assert fake_service.updated == (vid, "Neue Frage", "p")


def test_update_vote_group_move_checks_the_target_gremium(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    """A move to another eligibleGroup needs manage rights there, not only here."""
    _as_principal(app, "vote.manage")
    vid = uuid4()
    r = client.patch(f"/api/votes/{vid}", json={"eligibleGroup": "asta"})
    assert r.status_code == 200
    assert fake_service.updated == (vid, None, "p")


def test_update_vote_conflict_409(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.manage")
    r = client.patch("/api/votes/00000000-0000-0000-0000-000000000000", json={})
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
