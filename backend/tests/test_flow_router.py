"""TDD: Flow-Router-Verdrahtung (T-14) — Auth fail-closed + problem+json-Contract.

Service via ``dependency_overrides`` ersetzt; DB-Pfade liegen in der Integration.
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
from app.modules.flow.router import (
    get_action_dispatcher,
    get_flow_service,
)
from app.modules.flow.schemas import TransitionOut, TransitionResult
from app.modules.flow.service import FlowService


class _FakeService:
    def __init__(self) -> None:
        self.fired: dict[str, object] | None = None

    async def available_transitions(self, application_id, principal):  # noqa: ANN001
        return [
            TransitionOut(
                id=uuid4(),
                fromStateId=uuid4(),
                toStateId=uuid4(),
                label={"de": "Einreichen"},
            )
        ]

    async def fire(self, application_id, transition_id, principal, *, note=None):  # noqa: ANN001
        self.fired = {
            "application_id": application_id,
            "transition_id": transition_id,
            "principal": principal,
            "note": note,
        }
        return TransitionResult(
            newStateId=uuid4(), statusEventId=uuid4(), dispatchedActions=["notify"]
        )


@pytest.fixture
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def app(fake_service: _FakeService) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_flow_service] = lambda: fake_service
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_principal(app: FastAPI, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="mgr", permissions=set(perms)
    )
    app.dependency_overrides[get_current_applicant] = lambda: None


# --------------------------------------------------------------------------- #
# GET /transitions
# --------------------------------------------------------------------------- #
def test_list_transitions_requires_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/applications/{uuid4()}/transitions").status_code == 401


def test_list_transitions_missing_perm_403(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.read")  # nicht .manage
    r = client.get(f"/api/applications/{uuid4()}/transitions")
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"


def test_list_transitions_ok(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.manage")
    r = client.get(f"/api/applications/{uuid4()}/transitions")
    assert r.status_code == 200
    assert len(r.json()) == 1


# --------------------------------------------------------------------------- #
# POST /transition
# --------------------------------------------------------------------------- #
def test_fire_requires_auth_401(client: TestClient) -> None:
    r = client.post(
        f"/api/applications/{uuid4()}/transition", json={"transitionId": str(uuid4())}
    )
    assert r.status_code == 401


def test_fire_ok_passes_note(
    app: FastAPI, client: TestClient, fake_service: _FakeService
) -> None:
    _as_principal(app, "application.manage")
    app_id, transition_id = uuid4(), uuid4()
    r = client.post(
        f"/api/applications/{app_id}/transition",
        json={"transitionId": str(transition_id), "note": "freigegeben"},
    )
    assert r.status_code == 200
    assert r.json()["dispatchedActions"] == ["notify"]
    assert fake_service.fired is not None
    assert fake_service.fired["application_id"] == app_id
    assert fake_service.fired["transition_id"] == transition_id
    assert fake_service.fired["note"] == "freigegeben"


def test_fire_rejects_bad_body_422(app: FastAPI, client: TestClient) -> None:
    _as_principal(app, "application.manage")
    r = client.post(
        f"/api/applications/{uuid4()}/transition", json={"transitionId": "not-a-uuid"}
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# DI factories
# --------------------------------------------------------------------------- #
def test_di_factories_build_real_objects() -> None:
    assert isinstance(get_action_dispatcher(), NullActionDispatcher)
    dispatcher = NullActionDispatcher()
    service = get_flow_service(session=object(), dispatcher=dispatcher)  # type: ignore[arg-type]
    assert isinstance(service, FlowService)
    assert service.dispatcher is dispatcher


# --------------------------------------------------------------------------- #
# OpenAPI contract
# --------------------------------------------------------------------------- #
def test_openapi_declares_flow_error_responses(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    get = spec["paths"]["/api/applications/{application_id}/transitions"]["get"]
    assert {"401", "403", "404"} <= set(get["responses"])
    post = spec["paths"]["/api/applications/{application_id}/transition"]["post"]
    assert {"400", "401", "403", "404", "409", "422"} <= set(post["responses"])
    assert "application/problem+json" in post["responses"]["409"]["content"]
