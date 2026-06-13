"""TDD: Voting-Router-Verdrahtung (T-15) — Auth fail-closed + problem+json-Contract.

Service via ``dependency_overrides`` ersetzt; DB-Pfade liegen in der Integration."""

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

    async def create(self, application_id, payload):  # noqa: ANN001
        return _vote_out("draft")

    async def open(self, vote_id, *, now):  # noqa: ANN001
        return _vote_out("open")

    async def get(self, vote_id):  # noqa: ANN001
        return _vote_out("open")

    async def get_scoped(self, vote_id, principal):  # noqa: ANN001
        # Scope-Gate liegt im echten Service; das Fake reicht durch wie get().
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


# --------------------------------------------------------------------------- #
# create / open / close — vote.manage
# --------------------------------------------------------------------------- #
def test_create_requires_auth_401(client: TestClient) -> None:
    assert client.post(f"/api/applications/{uuid4()}/votes", json={}).status_code == 401


def test_create_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "vote.cast")  # nicht .manage
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


# --------------------------------------------------------------------------- #
# ballot — vote.cast (Gruppe prüft der Service)
# --------------------------------------------------------------------------- #
def test_ballot_requires_auth_401(client: TestClient) -> None:
    r = client.post(f"/api/votes/{uuid4()}/ballot", json={"choice": "yes"})
    assert r.status_code == 401


def test_ballot_gate_is_auth_only(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    # #delegation-rework: das Gate prüft nur Auth — externe Stellvertreter haben
    # kein globales vote.cast; die Autorisierung (vote.cast+Gruppe bzw.
    # Delegations-Zeile) liegt im Service (Unit-Tests dort).
    _as_principal(app, "vote.manage")  # nicht .cast
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


# --------------------------------------------------------------------------- #
# get — jeder Principal
# --------------------------------------------------------------------------- #
def test_get_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/votes/{uuid4()}").status_code == 401


def test_get_ok(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)  # nur eingeloggt nötig
    r = client.get(f"/api/votes/{uuid4()}")
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# DI factories + OpenAPI contract
# --------------------------------------------------------------------------- #
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
    """#vote-progress: cast broadcastet den Live-Zähler — ohne Event blieb
    »N von M abgestimmt« bei allen Clients bis zum Reload stale."""
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
    assert len(pub.tallies) == 1  # frischer Stand nach der Stimme
